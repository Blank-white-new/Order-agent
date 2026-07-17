# Code switching

A mixed utterance contains supported features from more than one language, normally Han and Latin text. Detection records `detected_locale=mixed`, retains the dominant concrete locale and replies once in that locale. It does not discard the other-language fragments or force the utterance through a single-language parser.

Examples covered by the curated data include “我要 two portions chicken leg rice 少辣 please”, “remove 雞髀飯 唔該”, “lemon tea 走冰 please”, and “delivery 去測試區”. Menu names may be resolved from any supported locale after preferred-locale matches. Safety scans all reviewed locale resources, so one clear risk phrase in any fragment remains effective.

An explicit switch inside mixed text overrides the automatic reply language and sets the lock. A single English item in a Chinese session, or a single Chinese item in an English session, does not switch the session. Locale switching preserves item codes, cart state and safety holds and never revives an old confirmation.
