# Voice editing requirements

Implementation status: requested, not yet implemented or validated.

- Speed is selectable; Japanese defaults to 0.84 and English/French/German to 0.9. Apply pitch-preserving tempo exactly once. Preserve natural silence.
- Full regeneration: edit the complete transcript and generate a new WAV, retain the previous version.
- Partial regeneration: select the faulty time interval in the current audio, edit only the relevant transcript, regenerate with enough surrounding linguistic context, and audition the replacement.
- Replacement must operate on the current project's audio version. Preserve the original audio and video.
- Do not assume a regenerated passage has the original duration. Offer fitting the selected interval or shifting subsequent video/subtitle timing; record the chosen operation and timing map.
- Join at appropriate quiet boundaries without cutting speech endings or removing natural pauses. Crossfades must not overlap spoken syllables. Audition joins before accepting.
- Replace only the selected interval; derive updated audio, video timing and subtitle timing consistently. Save undo information and the model/style/tempo/reference parameters.
- Whole-document or partial regeneration is explicit in the UI. Synthetic/local checks do not certify teacher timbre, pronunciation or seamlessness; GPU audition is pending.
