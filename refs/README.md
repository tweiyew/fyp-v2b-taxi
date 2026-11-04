# References

The papers this project cites. Any sentence about Paper A or Paper B in the report needs a page number from these files (`docs/PLAN.md`, guardrails).

The PDFs are gitignored: two are IEEE copies licensed to the NTU library, so they stay on this machine. Get your own copy from the link to rebuild the folder.

Page numbers: Paper A uses the PDF's own pages (1 to 7, the arXiv copy has no journal pages). Paper B and the review use the printed journal or proceedings pages.

## Paper A: the simulator

`paper-a-yuhas-2025-ev-taxi-fleet-charging.pdf`

M. Yuhas, R. K. Ahir, L. V. T. Hartono, M. D. D. Putranto, A. Easwaran, S. H. Supangkat, "Managing Charging Induced Grid Stress and Battery Degradation in Electric Taxi Fleets", arXiv:2510.19293v1, 22 Oct 2025. https://arxiv.org/abs/2510.19293 . `CLAUDE.md` gives the venue as ISGT-Asia 2025; the PDF itself does not name one.

Role: the taxi fleet simulator this repo forks.

| Page | What it says |
| --- | --- |
| 1 | Abstract: full-rate charging raises grid stress and battery wear; compares the 80-20 policy with an RL charging policy on NYC taxi data |
| 3 | Section III, long-horizon model: C_v(t), the C-rate used to charge or discharge a battery in [t-1, t) |
| 5 | Fleet of 50 taxis in NYC with 2 charging stations |
| 6 | Transfer to the City of Chicago Taxi Rides dataset |
| 7 | Future work: "better model technologies like vehicle-to-grid, and demand response". The paper has no V2G; the repo's V2G code came with Raditya's fork |

## Paper B: false data in EV charging

`paper-b-basumatary-2025-fdi-detection-narx.pdf`

H. Basumatary, M. Khatua, S. Nath, "False Data Injection Attack Detection in EV Charging Network Using NARX Neural Network", IEEE Transactions on Transportation Electrification, vol. 11, no. 4, pp. 9686-9700, Aug. 2025. doi:10.1109/TTE.2025.3553391

Role: the August proposal's source for the reporting channel and for detection numbers (`docs/PLAN.md`, P2 and P3; `docs/RESEARCH_PLAN.md`, SQ4).

| Page | What it says |
| --- | --- |
| 9686 | Abstract: a NARX network estimates the kWh delivered to an EV in a charging session; the estimation error is screened with the interquartile range; 99.40% detection accuracy against 88.68% and 98% for earlier schemes. Charging only, no discharge |
| 9687, 9691 | User input values (such as total energy demand) given to the charger to schedule a session: the "user-input channel" of `docs/PLAN.md` P2 |
| 9694 | A user who skips the mobile app gets default input values |

Not found by text search on 4 Nov: the "263 alarms for 196 attacks" that `docs/PLAN.md` (P3) attributes to Paper B. It may sit in a table or figure; find the page before citing it.

## Background: V2G and V2B review

`review-frattale-mascioli-2025-v2g-v2b.pdf`

L. Frattale Mascioli, A. Golino, R. Loggia, A. Bonfiglio, M. Minetti, A. L. Palma, C. Moscatiello, M. C. Falvo, L. Martirano, "Vehicle-to-Grid and Vehicle-to-Building Systems Integrated in Smart Infrastructures: A Comprehensive Review of Technologies, Challenges and Opportunities", 2025 International Conference on Clean Electrical Power (ICCEP), pp. 631-645. doi:10.1109/ICCEP65222.2025.11143653

Role: why a taxi would give power to a building at all. The PDF's text layer is garbled, so search does not work; read it as pages.

| Page | What it says |
| --- | --- |
| 631 | V2G lets EVs "feed energy back during peak demand periods"; services include load balancing and peak shaving |
| 632 | EVs were "regarded as just electric loads" with one-way charging; bidirectional charging allows charging and discharging; V2X covers V2V, V2B, V2H and V2G; EVs store energy at low demand and "return it at peak times" |
