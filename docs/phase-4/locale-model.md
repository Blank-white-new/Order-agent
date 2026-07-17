# Locale model

`LocaleContext` is immutable and contains `requested_locale`, `detected_locale`, `dominant_locale`, `response_locale`, `mixed_language`, `confidence`, `locale_locked`, and `detected_scripts`.

The supported concrete reply locales are `zh-CN`, `yue-Hant-HK`, and `en-HK`. `mixed` is a detected input property. Unsupported scripts or explicit unsupported-language names produce detected locale `und` and the Phase 3 `LANGUAGE_UNSUPPORTED` handoff; they are never silently treated as Mandarin.

Explicit commands such as “请说普通话”, “轉做廣東話”, and “English please” take precedence and lock the concrete response locale. A later explicit command may change it again. A single menu name in another supported language does not switch the session. For mixed input the detector retains both script evidence and a deterministic dominant locale; the dominant locale becomes the reply locale unless the customer has selected or locked another locale.

Auto detection and Assisted reply selection are distinct modes. Auto receives no locale fields. Assisted receives one concrete selected reply locale plus a lock; `mixed` can never be selected as a reply locale. Pure traditional standard Chinese without colloquial Cantonese or Mandarin markers is intrinsically ambiguous from text alone. Such cases preserve the current concrete reply locale and are reported separately rather than forced into exact-locale accuracy.

`ConversationSession.locale` persists the concrete response locale. Session state also persists requested, detected, dominant and response locales plus the locked and mixed flags. Restoring a pre-Phase-4 session derives safe defaults from its existing locale. Sessions and tenants never share locale state.

Changing locale does not clear order items, alter authoritative item codes, resolve a handoff, reinstate a stale confirmation, or change `draft_version` unless the same utterance independently performs an allowed order change. Detection confidence has no safety authority.
