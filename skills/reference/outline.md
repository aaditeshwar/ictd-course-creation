# Outline: Climate Resilience Tools and Participatory Vulnerability Assessment for Rural Livelihoods

Deck file: `climate_resilience_lecture_v2.pptx` (18 slides). This outline reconstructs the actual
built deck's structure, topic-by-topic, plus the appendix requests it implies -- some of which
were only ever captured in speaker notes as editorial asides, not as visible on-slide callouts.
Retrofitted here per the v3 pipeline convention (`skill_lecture_deck_building.md` \u00a78) so
every appendix-worthy point is tracked in one place, not scattered.

## Slide-by-slide

| # | Section | Title | Content | Figure |
|---|---|---|---|---|
| 1 | Title | Climate Resilience Tools | -- | -- |
| 2 | Framing | The MGNREGA backbone | Scheme mechanics + case-study-wide stats | none |
| 3 | Problem Discovery | How do you actually assess climate vulnerability? | CoDriVE's 5-step method | CoDriVE handbook, Fig. 6 (p.44) or Fig. 7 (p.51) |
| 4 | Problem Discovery | Grounding it in real villages and real institutions | SEAF framework + Panchayat governance | none identified |
| 5 | Problem Discovery (brief) | Two more angles on the same problem | Retrospective assessment + Fischer's baseline | none |
| 6 | Computing Elements | Sensing physical climate risk, not just social risk | Kwajalein overwash mechanism | Kwajalein paper, Fig. 1 (p.3) or Fig. 2 (p.4) |
| 7 | Computing Elements | Structured household-level data collection | Rwanda survey methodology | Rwanda paper, Fig. 1 (p.2) or Fig. 4 (p.3) |
| 8 | Ethnographic Design | Designing with Gram Panchayats, not just for them | CRISP-M co-design process | CRISP-M paper, Fig. 5/9/12 (p.19-26) |
| 9 | Ethnographic Design | Turning a community's demand into a geo-tagged request | Commons Connect + Bhuvan portal | ICTD 2024 paper, Fig. 1 (p.5) or Fig. 5 (p.13) |
| 10 | Ethnographic Design (callback) | The earlier readings are design examples too | Synthesis, no new source | none |
| 11 | Socio-technical Dynamics | Decentralization is a design choice, not a default | Fischer + editorial synthesis | none |
| 12 | Impact Evaluation | What did the first field test actually reveal? | ICTD 2024 field-testing observations | ICTD 2024 paper, Fig. 6/8/10 (p.25-28) |
| 13 | Impact Evaluation | The one reading with real quantitative outcomes | Fischer's poorer-households finding | Fischer paper, Fig. 8 (p.8) |
| 14 | Impact Evaluation (brief) | A baseline, not yet an evaluation | Kwajalein reframed honestly | none |
| 15 | Operations & Scale | An early-warning system has to keep running | CRISP-M's SPI-triggered monitoring | CRISP-M paper, Fig. 13/14 (p.28-29) |
| 16 | Operations & Scale | Who keeps this running across hundreds of villages | CSO coordination model + honest gap (Commons Connect review still unfetched) | none |
| 17 | Synthesis | One pipeline, six lenses | Recap table | none |
| 18 | Discussion | -- | 3 prompts tied to Slides 11, 13, 9+15 | none |

## Appendix Requests

Eight targeted requests, picked for slides where real depth existed in the source material but
had to be compressed to fit a slide -- not one per slide. Slides 2, 5, 10, 11, 14, 16, 17, 18 are
deliberately excluded: either synthesis-only, too thin on source, or already at the right depth
for a slide.

- reading: 2023_community_driven_vulnerability_evaluation_ce5f34
  topic: problem_discovery
  ask: "Full 5-step method, especially how the Vulnerability Code is computed from Drivers/Pressures/State/Trends"
- reading: 2023_community_consultation_on_natural_resource_management_ed670f
  topic: problem_discovery
  ask: "Full structure of the SEAF framework across its four channels (civil-society action, public investment, corporate decision-making, policy), and the complete list of common property resources it targets"
- reading: ghtc_2022_climate_focused_field_research_within_the
  topic: cs_fundamentals
  ask: "The overwash contamination modeling scenarios -- specific salinity thresholds (250mg/L) and sea-level-rise/consecutive-event conditions under which groundwater contamination becomes likely"
- reading: ghtc_2023_towards_a_geospatial_household_natural_hazard
  topic: cs_fundamentals
  ask: "The four-factor household resilience model (physical vulnerability, financial capacity, information access, technological capacity) and how the XLSForm/Survey123 questionnaire operationalizes each factor"
- reading: bharadwaj_crisp_m_mgnrega
  topic: ethnographic_design
  ask: "The full co-development process across the 12 government institutions involved, from data generation to final users"
- reading: ictd_2024_initial_observations_from_field_testing_of
  topic: ethnographic_design
  ask: "The complete list of Bhuvan portal data layers and how the resource-mapping workflow sequences them into a geo-tagged demand"
- reading: fischer_pro_poor_climate_mgnrega
  topic: impact_evaluation
  ask: "The governance-conditions analysis methodology behind the 1,400-household/798-project dataset -- what local governance factors were measured and how they were linked to outcomes"
- reading: bharadwaj_crisp_m_mgnrega
  topic: operations_scale
  ask: "Exact SPI/NDVI/VCI/RSI/MAI computation definitions and thresholds, and how the 24-48 hour indicator updates feed the drought-declaration trigger"

Note: `bharadwaj_crisp_m_mgnrega` appears twice with different `topic`/`ask` pairs (design
process vs. monitoring internals) -- `appendix_writer.py` treats each list entry as an
independent request, so both get their own section rather than colliding.
