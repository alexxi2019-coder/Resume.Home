# Local PDF dependencies

`pdf_export/` contains ReportLab 5.0.1, Pillow 12.3.0, and charset-normalizer 3.5.2 built for Windows Python 3.13. Their package license files are included in their `.dist-info/licenses` directories. Resume.Home uses these packages for PDF export. PDF preview uses `pypdfium2` from `requirements.txt`.

`pdf-deps.zip` contains unmodified Python source for pypdf 6.10.0 and typing_extensions from the bundled Codex Python runtime, with bytecode omitted. Licenses are included beside the archive. Python's zip importer loads these packages only inside the isolated PDF parser process. This keeps the existing `python3 -B app.py` startup working without pip or a network connection on Python 3.9+.

pypdf is BSD-3-Clause licensed; typing_extensions uses the Python Software Foundation license. No cryptography, OCR, or external AI dependency is bundled. Password-protected PDFs are rejected with an explanation. To update, replace the archive from a reviewed compatible release and update licenses/version notes, then run all resume extraction tests with the minimum supported Python version.
