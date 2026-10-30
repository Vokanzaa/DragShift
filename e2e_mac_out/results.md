# DragShift macOS end-to-end — 0/17 passed

| # | Scenario | Result | Detail | Time |
|---|---|---|---|---|
| 1 | JPG → PNG | ❌ | AssertionError: no output file appeared | 24.3s |
| 2 | JPG → WEBP | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 3 | JPG → HEIC | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 4 | JPG → PDF | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 5 | PNG → JPG | ❌ | AssertionError: no output file appeared | 23.5s |
| 6 | PDF → JPG (3 pages) | ❌ | AssertionError: no output file appeared | 23.0s |
| 7 | PDF → TXT | ❌ | KeyError: 'D-Report.pdf' | 0.1s |
| 8 | DOCX → PDF | ❌ | AssertionError: no output file appeared | 23.3s |
| 9 | PDF Split | ❌ | KeyError: 'D-Report.pdf' | 0.1s |
| 10 | PDF Rotate | ❌ | KeyError: 'D-Report.pdf' | 0.2s |
| 11 | PDF Compress | ❌ | KeyError: 'D-Report.pdf' | 0.1s |
| 12 | Merge 2 PDFs | ❌ | KeyError: 'D-Report.pdf' | 1.5s |
| 13 | Compress (window, Enter) | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 14 | Resize 50% (window, Enter) | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 15 | Add BG (window, Enter) | ❌ | KeyError: 'D-Graphic.png' | 0.1s |
| 16 | Metadata: remove all (Enter) | ❌ | KeyError: 'D-Photo.jpg' | 0.1s |
| 17 | Slices filled before the mouse moves | ❌ | pasteboard not read | 0s |