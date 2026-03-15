# AI Integration Ideas

This platform serves caregivers and parents of autistic children. The AI integrations below leverage existing model data to enhance the experience at every stage.

## During Assessment (UserSurvey + UserAnswer)

### Adaptive Questioning
AI watches the answer stream in real-time. If early answers strongly indicate a specific developmental profile (Classification), it prioritizes remaining questions that sharpen that classification rather than asking redundant ones. Builds on existing `allow_end_based_on_answer_repeat` and `ending_option` logic.

### Gentle Pacing
Detect when a caregiver is struggling (long pauses between answers, tab switches via TabSwitchEvent). AI surfaces an encouraging message or suggests taking a break. These assessments are emotionally heavy.

### Clarification on Demand
Parent doesn't understand a question. AI explains it in plain language, in their language, using the Question translations and context from surrounding questions.

## After Assessment (Classifications + Recommendations + Actions)

### Narrative Report
Instead of "Classification: High Sensory Sensitivity, Score: 78", the AI generates:

> "Based on your answers, your child shows heightened sensory awareness. This is common and manageable. Here's what this means day-to-day..."

Written in warm, non-clinical Arabic (or the caregiver's language). The existing `generate_report` mutation is the hook for this.

### Personalized Action Plans
Actions have `upper_limit`/`lower_limit` score ranges. AI takes the raw action + its translations and expands it into a concrete daily/weekly plan tailored to the child's profile:

> "For the next two weeks, try limiting screen time to 30 minutes and introducing one new texture during meals."

### Material Recommendations
The Recommendable model stores items from external services. AI ranks and explains *why* a specific course, article, or video is relevant to *this* child's profile:

> "This video on sensory integration is recommended because your child scored high on tactile sensitivity."

## Longitudinal (Across Multiple UserSurveys Over Time)

### Progress Tracking
Parent re-takes assessment months later. AI compares UserSurveyClassification counts and scores across snapshots:

> "Your child's communication score improved from 45 to 62 since March. The social interaction strategies seem to be working."

### Adjusted Recommendations
As classifications shift over time, AI updates which Actions and Materials are most relevant now vs. 6 months ago.

### Early Alerts
If scores regress in a specific area, AI flags it gently and suggests consulting a specialist.

## For Professionals Building Assessments

### Question Validation
AI reviews questions for cultural sensitivity, clarity in Arabic, and whether the scoring logic makes clinical sense.

### Classification Calibration
Suggest score boundaries for Classifications based on established developmental scales.

## MCP Server

Expose this service as an MCP tool provider so AI agents can:
- Create/manage surveys, sections, questions via mutations
- Enroll users and submit answers programmatically
- Pull results, classifications, recommendations
- Generate surveys from natural language descriptions

## Architecture

- `ai/` Django app with its own models (prompts, generation history, costs)
- Service layer calling AI provider (Claude API)
- MCP server as a separate entry point alongside GraphQL
- Feature flags for AI features (cost implications)

## Recommended Starting Point

**Narrative report generation** — it's where caregivers feel the most lost (raw scores mean nothing to a worried parent), and the `generate_report` mutation is already wired up.