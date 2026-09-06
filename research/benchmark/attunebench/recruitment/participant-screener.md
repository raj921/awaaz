# Participant screener — use BEFORE booking anyone

Goal: confirm eligibility for the right language slice and record the facts the
schema needs (participant_id, age_band, native_language, additional_languages).
Keep it under 3 minutes. No PII beyond what consent covers; do not record names
in this screener.

Send as a WhatsApp message or ask verbally; log answers in collection-tracker.csv.

1. Which language(s) do you speak daily at home? (Telugu / Hindi / English / other)
2. Which language do you consider your native/mother tongue?
3. Are you 18 or older? Age band: 18-24 / 25-34 / 35-44 / 45-54 / 55+
4. Where did you mostly grow up? (city/region — for dialect spread, no address)
5. Would you chat: (a) with a friend you bring, or (b) with our interviewer?
6. Voice recording okay? Yes / No (text-only conversation is fine)
7. Comfortable signing the consent form? (withdrawal available anytime)
8. Topics you enjoy talking about? (work/school, family, friends, health,
   money, hobbies, learning, celebrations — helps us balance topics)

## Assignment rules

- Native Hindi at home + Hindi mother tongue -> `hi` slice
- Native Telugu at home + Telugu mother tongue -> `te` slice
- Romanized Hindi-English in daily use -> `hinglish` slice
- Telugu-English mix or Hindi-Telugu mix -> `tenglish`/`mixed` slice
- Hesitant on consent or under 18 -> exclude politely, log as excluded with reason

## After screening

- Send the consent form (attunebench/consent-form.md) and record `consent_id`
- Schedule the session; log participant + status in collection-tracker.csv
- After the session: transcript -> validate.py -> collection checklist
