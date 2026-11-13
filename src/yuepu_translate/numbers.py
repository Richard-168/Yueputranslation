"""Explicit number readings for Mandarin speech; never rewrites displayed text."""

import re
from decimal import Decimal

import cn2an

NUMBER = re.compile(r"(?<![0-9.])[0-9]+(?:\.[0-9]+)?(?![0-9.])")


def exact_chinese_amount(text):
    # cn2an's strict whole-string parser rejected its own 150.50 rendering in
    # this environment. Parse the fractional digits independently as strings;
    # never pass a monetary fixture through binary floating point.
    integer, point, fraction = text.partition("点")
    recovered = str(cn2an.cn2an(integer, "strict"))
    if point:
        digits = "零一二三四五六七八九"
        if not fraction or any(c not in digits for c in fraction):
            raise ValueError("Unexpected Chinese fraction spelling")
        recovered += "." + "".join(str(digits.index(c)) for c in fraction)
    return Decimal(recovered)


def spoken_numbers(text, mode):
    if mode not in {"amount", "identifier"}:
        raise ValueError("Explicit fixture number mode required")
    edits = []

    def replace(match):
        raw = match.group(0)
        if mode == "identifier" and "." in raw:
            raise ValueError("Decimal identifiers are outside this experiment")
        rendered = cn2an.an2cn(raw, "direct" if mode == "identifier" else "low")
        if mode == "identifier":
            recovered = cn2an.cn2an(rendered, "direct")
            if recovered != raw:
                raise ValueError("Identifier digits or leading zeros changed")
        else:
            recovered = exact_chinese_amount(rendered)
            if recovered != Decimal(raw):
                raise ValueError("Amount value changed")
        edits.append(dict(original=raw, spoken=rendered, recovered=str(recovered)))
        return rendered

    return NUMBER.sub(replace, text), edits
