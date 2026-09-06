
## 2026-09-05 — Part 33: Voice 400 diagnosed — long clip + generic error

- User's voice turn 400d: body past the 4 MiB middleware cap (long recording), misreported as "invalid request body". Fixed both ends: frontend auto-stops recording at 30 s; backend names MaxBytesError honestly ("request body too large, keep clips under 30 seconds", verified live with a 5 MB probe). gofmt/vet/build/tests + frontend build green.
