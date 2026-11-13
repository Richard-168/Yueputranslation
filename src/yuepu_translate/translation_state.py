"""Translate immutable source prefixes once; replace only a small draft tail."""


class IncrementalTranslation:
    def __init__(self):
        self.source = self.target = ""
        self.preview_source = self.preview_target = ""
        self.speech = []

    def _translate(self, text, translate):
        if not text.strip():
            return ""
        if text == self.preview_source:
            return self.preview_target
        parts = []
        while text:
            cut = min(len(text), 96)
            if len(text) > cut:
                boundary = max(text.rfind(c, 0, cut) for c in "。！？；，.!?;\n ")
                if boundary >= 24:
                    cut = boundary + 1
            part, text = text[:cut], text[cut:]
            if part.strip():
                parts.append(translate(part))
        return "".join(parts)

    def update(self, frozen_source, tail, translate, *, preview=True):
        if not frozen_source.startswith(self.source):
            raise ValueError("已固定的原文不能被后续翻译改写。")
        delta = frozen_source[len(self.source) :]
        if delta:
            translated = self._translate(delta, translate)
            self.source = frozen_source
            self.target += translated
            if translated:
                self.speech.append(translated)
            # A promoted draft is now part of the fixed prefix, not its tail.
            self.preview_source = self.preview_target = ""
        if not tail.strip():
            self.preview_source = self.preview_target = ""
        elif preview and tail != self.preview_source:
            translated = self._translate(tail, translate)
            self.preview_source, self.preview_target = tail, translated
        return self.target + self.preview_target
