#include <jni.h>
#include "llama.h"
#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;

// JNI modified UTF-8 differs from model UTF-8 for supplementary characters.
std::string utf8(JNIEnv *env, jstring value) {
    if (!value) throw std::invalid_argument("Missing text");
    const jsize length = env->GetStringLength(value);
    const jchar *chars = env->GetStringChars(value, nullptr);
    if (!chars) throw std::runtime_error("Text allocation failed");
    std::string result;
    for (jsize i = 0; i < length; ++i) {
        uint32_t c = chars[i];
        if (c >= 0xD800 && c <= 0xDBFF) {
            if (i + 1 >= length || chars[i + 1] < 0xDC00 || chars[i + 1] > 0xDFFF) {
                env->ReleaseStringChars(value, chars);
                throw std::invalid_argument("Invalid Unicode text");
            }
            c = 0x10000 + ((c - 0xD800) << 10) + chars[++i] - 0xDC00;
        } else if (c >= 0xDC00 && c <= 0xDFFF) {
            env->ReleaseStringChars(value, chars);
            throw std::invalid_argument("Invalid Unicode text");
        }
        if (c < 0x80) result.push_back(static_cast<char>(c));
        else if (c < 0x800) {
            result.push_back(static_cast<char>(0xC0 | (c >> 6)));
            result.push_back(static_cast<char>(0x80 | (c & 63)));
        } else if (c < 0x10000) {
            result.push_back(static_cast<char>(0xE0 | (c >> 12)));
            result.push_back(static_cast<char>(0x80 | ((c >> 6) & 63)));
            result.push_back(static_cast<char>(0x80 | (c & 63)));
        } else {
            result.push_back(static_cast<char>(0xF0 | (c >> 18)));
            result.push_back(static_cast<char>(0x80 | ((c >> 12) & 63)));
            result.push_back(static_cast<char>(0x80 | ((c >> 6) & 63)));
            result.push_back(static_cast<char>(0x80 | (c & 63)));
        }
    }
    env->ReleaseStringChars(value, chars);
    return result;
}

jstring javaString(JNIEnv *env, const std::string &text) {
    std::vector<jchar> chars;
    for (size_t i = 0; i < text.size();) {
        uint32_t c = static_cast<unsigned char>(text[i++]);
        int remaining = 0;
        if ((c & 0xE0) == 0xC0) { c &= 31; remaining = 1; }
        else if ((c & 0xF0) == 0xE0) { c &= 15; remaining = 2; }
        else if ((c & 0xF8) == 0xF0) { c &= 7; remaining = 3; }
        else if (c >= 0x80) throw std::runtime_error("Invalid model text");
        for (int j = 0; j < remaining; ++j) {
            if (i >= text.size() || (static_cast<unsigned char>(text[i]) & 0xC0) != 0x80)
                throw std::runtime_error("Incomplete model text");
            c = (c << 6) | (static_cast<unsigned char>(text[i++]) & 63);
        }
        if (c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF))
            throw std::runtime_error("Invalid model text");
        if (c < 0x10000) chars.push_back(static_cast<jchar>(c));
        else {
            c -= 0x10000;
            chars.push_back(static_cast<jchar>(0xD800 | (c >> 10)));
            chars.push_back(static_cast<jchar>(0xDC00 | (c & 1023)));
        }
    }
    return env->NewString(chars.data(), static_cast<jsize>(chars.size()));
}

struct Engine {
    std::unique_ptr<llama_model, decltype(&llama_model_free)> model{nullptr, llama_model_free};
    std::unique_ptr<llama_context, decltype(&llama_free)> context{nullptr, llama_free};
    std::atomic<bool> cancelled{false};
    std::mutex inference;
    Clock::time_point deadline = Clock::time_point::max();

    static bool abort(void *data) {
        auto *self = static_cast<Engine *>(data);
        return self->cancelled.load() || Clock::now() > self->deadline;
    }

    Engine(const std::string &path, int threads) {
        auto params = llama_model_default_params();
        params.n_gpu_layers = 0;
        params.load_mode = LLAMA_LOAD_MODE_MMAP;
        model.reset(llama_model_load_from_file(path.c_str(), params));
        if (!model) throw std::runtime_error("Translation model could not be loaded");
        auto config = llama_context_default_params();
        config.n_ctx = 2048;
        config.n_batch = 512;
        config.n_ubatch = 512;
        config.n_threads = threads;
        config.n_threads_batch = threads;
        config.no_perf = true;
        config.abort_callback = abort;
        config.abort_callback_data = this;
        context.reset(llama_init_from_model(model.get(), config));
        if (!context) throw std::runtime_error("Translation context could not be created");
    }

    std::string translate(const std::string &text, bool toMandarin) {
        std::lock_guard<std::mutex> lock(inference);
        if (cancelled.load()) throw std::runtime_error("Cancelled");
        deadline = Clock::now() + std::chrono::seconds(30);
        const std::string target = toMandarin ? u8"中文" : u8"粤语";
        const std::string prompt = u8"<｜hy_begin▁of▁sentence｜><｜hy_User｜>将以下文本翻译为" + target +
            u8"，注意只需要输出翻译后的结果，不要额外解释：\n\n" + text + u8"<｜hy_Assistant｜>";
        const auto *vocab = llama_model_get_vocab(model.get());
        std::vector<llama_token> tokens(prompt.size() + 16);
        const int count = llama_tokenize(vocab, prompt.data(), static_cast<int>(prompt.size()),
            tokens.data(), static_cast<int>(tokens.size()), false, true);
        if (count <= 0 || count > 1700) throw std::invalid_argument("Text exceeds translation context");
        tokens.resize(count);
        llama_memory_clear(llama_get_memory(context.get()), true);
        for (int offset = 0; offset < count; offset += 512) {
            const int size = std::min(512, count - offset);
            if (abort(this) || llama_decode(context.get(), llama_batch_get_one(tokens.data() + offset, size)) != 0)
                throw std::runtime_error(cancelled.load() ? "Cancelled" : "Translation timed out");
        }
        auto samplerParams = llama_sampler_chain_default_params();
        samplerParams.no_perf = true;
        std::unique_ptr<llama_sampler, decltype(&llama_sampler_free)> sampler(
            llama_sampler_chain_init(samplerParams), llama_sampler_free);
        llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_k(20));
        llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_p(.6f, 1));
        llama_sampler_chain_add(sampler.get(), llama_sampler_init_penalties(llama_vocab_n_tokens(vocab), 64, 1.05f, 0, 0));
        llama_sampler_chain_add(sampler.get(), llama_sampler_init_temp(.7f));
        llama_sampler_chain_add(sampler.get(), llama_sampler_init_dist(42));
        std::string result;
        for (int i = 0; i < 192; ++i) {
            if (abort(this)) throw std::runtime_error(cancelled.load() ? "Cancelled" : "Translation timed out");
            llama_token token = llama_sampler_sample(sampler.get(), context.get(), -1);
            if (llama_vocab_is_eog(vocab, token)) {
                if (result.empty()) throw std::runtime_error("Empty translation");
                return result;
            }
            char buffer[1024];
            const int size = llama_token_to_piece(vocab, token, buffer, sizeof(buffer), 0, false);
            if (size < 0 || size > static_cast<int>(sizeof(buffer))) throw std::runtime_error("Invalid translation token");
            result.append(buffer, size);
            if (result.size() > 8192) throw std::runtime_error("Translation output exceeds limit");
            if (llama_decode(context.get(), llama_batch_get_one(&token, 1)) != 0)
                throw std::runtime_error(cancelled.load() ? "Cancelled" : "Translation failed");
        }
        throw std::runtime_error("Translation did not finish within its output limit");
    }
};

std::mutex handlesMutex;
std::unordered_map<jlong, std::shared_ptr<Engine>> handles;
std::atomic<jlong> nextHandle{1};
std::once_flag initialized;

std::shared_ptr<Engine> lookup(jlong handle) {
    std::lock_guard<std::mutex> lock(handlesMutex);
    auto item = handles.find(handle);
    if (item == handles.end()) throw std::runtime_error("Translation engine is closed");
    return item->second;
}

void failure(JNIEnv *env, const std::exception &error) {
    // No prompt, recognized content, file paths or model logs are included.
    env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), error.what());
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_org_yuepu_translate_engine_NativeTranslator_create(JNIEnv *env, jobject, jstring path, jint threads) {
    try {
        if (threads < 1 || threads > 8) throw std::invalid_argument("Invalid thread count");
        std::call_once(initialized, [] {
            llama_log_set([](ggml_log_level, const char *, void *) {}, nullptr);
            llama_backend_init();
        });
        auto engine = std::make_shared<Engine>(utf8(env, path), threads);
        const jlong id = nextHandle.fetch_add(1);
        std::lock_guard<std::mutex> lock(handlesMutex);
        handles.emplace(id, std::move(engine));
        return id;
    } catch (const std::exception &error) { failure(env, error); return 0; }
}

extern "C" JNIEXPORT jstring JNICALL
Java_org_yuepu_translate_engine_NativeTranslator_translate(JNIEnv *env, jobject, jlong handle, jstring text, jboolean toMandarin) {
    try {
        if (!text || env->GetStringLength(text) < 1 || env->GetStringLength(text) > 240)
            throw std::invalid_argument("Translation accepts 1-240 characters");
        return javaString(env, lookup(handle)->translate(utf8(env, text), toMandarin));
    } catch (const std::exception &error) { failure(env, error); return nullptr; }
}

extern "C" JNIEXPORT void JNICALL
Java_org_yuepu_translate_engine_NativeTranslator_cancel(JNIEnv *, jobject, jlong handle) {
    try { lookup(handle)->cancelled.store(true); } catch (const std::exception &) {}
}

extern "C" JNIEXPORT void JNICALL
Java_org_yuepu_translate_engine_NativeTranslator_reset(JNIEnv *env, jobject, jlong handle) {
    try {
        auto engine = lookup(handle);
        std::lock_guard<std::mutex> lock(engine->inference);
        engine->cancelled.store(false);
    } catch (const std::exception &error) { failure(env, error); }
}

extern "C" JNIEXPORT void JNICALL
Java_org_yuepu_translate_engine_NativeTranslator_destroy(JNIEnv *, jobject, jlong handle) {
    std::lock_guard<std::mutex> lock(handlesMutex);
    auto item = handles.find(handle);
    if (item != handles.end()) { item->second->cancelled.store(true); handles.erase(item); }
}
