# Free Kaggle GPU VoxCPM2 setup

This is an optional cloud batch workflow for the Windows Studio. It does not install VoxCPM2 or PyTorch on the user's computer and does not change the installed 0.12.11 version.

## What the Studio integration does

1. The user enters a Kaggle username and the slug of the private Dataset containing the authorized 1626 teacher reference WAV.
2. The user saves their Kaggle API key in the Windows Credential Manager through the Studio UI. The key is not written into the Studio JSON settings or submitted in the Notebook code.
3. The Studio creates a unique private Kaggle Notebook for the text, enables GPU and Internet, and references the private 1626 Dataset.
4. The Notebook runs openbmb/VoxCPM2 with `reference_wav_path` set to 1626, and `prompt_wav_path` and `prompt_text` left empty. It writes a PCM 16-bit WAV.
5. The Studio downloads the WAV into the selected output folder, selects it as the new audio input, then deletes the private job Notebook and local temporary request files.

The Japanese template is not used as clone input. Users should run the Studio's existing audio review/denoise and video export steps after generation.

## Account and data setup

- Each team member needs their own Kaggle account and API key if each should use an independent weekly quota. One shared Kaggle account shares one account's quota and credential.
- The 1626 reference audio must be kept in a private Kaggle Dataset. Grant Dataset access to every account that will submit generation jobs. Never add teacher audio to this public source repository or a public Dataset.
- Kaggle API tokens must be entered only in the Studio's secure credential field. Do not send tokens in chat or commit them to a repository.
- Submitted text is placed in a private, per-job Notebook. The integration deletes that Notebook after retrieving the WAV, including on failure where possible. Kaggle may retain execution records under its own service policies.

## Free compute limits and trade-offs

Kaggle's official notebook documentation currently lists free P100 GPU access, up to 30 GPU hours per week, and up to 9 hours per session. Availability and queue times can change. This is a Notebook job workflow, not an always-on inference API; model installation and weights may be downloaded again for each job. First use must confirm the current Kaggle runtime can install and run VoxCPM2 on the allocated GPU.

This option is intended to improve on a five-minute-per-day serverless GPU cap while avoiding paid compute. It still needs account-level credentials and private Dataset access, and it should not be advertised as unlimited or guaranteed.
