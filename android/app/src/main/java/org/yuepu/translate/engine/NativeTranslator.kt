package org.yuepu.translate.engine

internal object NativeTranslator {
    init { System.loadLibrary("yuepu_native") }
    external fun create(path: String, threads: Int): Long
    external fun translate(handle: Long, text: String, toMandarin: Boolean): String
    external fun cancel(handle: Long)
    external fun reset(handle: Long)
    external fun destroy(handle: Long)
}
