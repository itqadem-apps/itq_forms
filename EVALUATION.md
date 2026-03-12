# Evaluation System

## Overview

The evaluation system computes results (scores, classifications, recommendations, actions) for submitted assessments. It supports two modes controlled by the `evaluation_type` field on the survey:

| Mode | Value | Behavior |
|------|-------|----------|
| **Automatic** | `automatic_evaluation` | Results computed immediately on submission |
| **Manual** | `manual_evaluation` | Admin reviews, scores answers, then triggers evaluation |

---

## Evaluation Pipeline

Both modes use the same core pipeline. The difference is **when** it runs.

### Per-Answer Scoring

For each `UserAnswer` with selected options:

| Question Type | Scoring Rule |
|---------------|-------------|
| Radio, Dropdown (single-select) | Score = selected option's `score` value |
| Checkbox (multi-select) | Score = sum of all selected options' `score` values |
| Radio Grid, Checkbox Grid | Score = sum of all selected options' `score` values (column options only have scores) |
| Text, Textarea, Number, File, Date, Time, DateTime | Score = 0 (no selectable options) |

Each answer's computed score is saved to `UserAnswer.score`.

### Aggregation

After all answers are scored:

1. **Total Score** — Sum of all per-answer scores → saved to `UserSurvey.score` (only when `use_score=true`, otherwise `null`)
2. **Classifications** — Collected from each selected option's `classification` FK, counted by frequency, sorted descending (most common first) → saved to `UserSurveyClassification` records
3. **Recommendations** — Collected from each selected option's linked recommendations, counted and deduplicated, sorted descending → saved to `UserSurveyRecommendation` records
4. **Actions** — Total score matched against `UserAction.lower_limit` / `upper_limit` ranges → matching action saved to `UserSurvey.action` FK

### Final State

After evaluation completes:
- `UserSurvey.evaluated_at` is set to the current timestamp
- `UserSurvey.score` is set (if `use_score=true`)
- `UserSurvey.action` is set (if `use_actions=true` and a range matches)
- `UserSurveyClassification` records are created (if `use_classifications=true`)
- `UserSurveyRecommendation` records are created (if `use_recommendations=true`)

---

## Feature Flags

All evaluation features are controlled by flags snapshotted from the survey at enrollment:

| Flag | Default | Effect |
|------|---------|--------|
| `is_evaluable` | `false` | Master flag — if false, no evaluation runs |
| `evaluation_type` | `automatic_evaluation` | Determines auto vs manual mode |
| `use_score` | `true` | Compute and store scores |
| `use_classifications` | `false` | Collect and aggregate classifications |
| `use_recommendations` | `false` | Collect and aggregate recommendations |
| `use_actions` | `false` | Match score against action ranges |

---

## Automatic Evaluation

### Flow

```
User answers questions
        ↓
User calls finishAssessment
        ↓
Server validates required questions
        ↓
Sets submitted_at, deletes unanswered questions
        ↓
evaluate_assessment() runs immediately
        ↓
Returns FinishAssessmentResult with score, classifications, recommendations
```

### GraphQL

```graphql
mutation FinishAssessment($userSurveyId: Int!) {
  finishAssessment(userSurveyId: $userSurveyId) {
    status            # "finished"
    score             # computed total score (or null)
    evaluatedAt       # ISO 8601 timestamp
    classifications {
      id
      count
      classification {
        id
        score
        translations { language, content { name } }
      }
    }
    recommendations {
      id
      count
      recommendation {
        id
        translations { language, content { description } }
      }
    }
  }
}
```

### Response States

| State | `submitted_at` | `evaluated_at` | `score` |
|-------|---------------|----------------|---------|
| In progress | `null` | `null` | `null` |
| Submitted + evaluated | set | set | computed |

---

## Manual Evaluation

### Flow

```
User answers questions
        ↓
User calls finishAssessment
        ↓
Server validates required questions
        ↓
Sets submitted_at, deletes unanswered questions
        ↓
Evaluation does NOT run (evaluation_type = manual)
        ↓
submitted_at is set, evaluated_at remains null
        ↓
Admin reviews answers
        ↓
Admin scores individual answers (scoreAnswer / scoreAnswersBatch)
        ↓
Admin calls evaluateManualAssessment (with optional overrides)
        ↓
evaluate_assessment() runs, aggregates per-answer scores
        ↓
Overrides applied if provided
        ↓
Returns FinishAssessmentResult
```

### Response States

| State | `submitted_at` | `evaluated_at` | `score` |
|-------|---------------|----------------|---------|
| In progress | `null` | `null` | `null` |
| Submitted, awaiting review | set | `null` | `null` |
| Evaluated by admin | set | set | computed or overridden |

---

### Step 1: Score Individual Answers

**Single answer:**

```graphql
mutation ScoreAnswer(
  $userSurveyId: Int!
  $answerId: Int!
  $score: Int!
) {
  scoreAnswer(
    userSurveyId: $userSurveyId
    answerId: $answerId
    score: $score
  ) {
    id
    score
    answer
    timeSpent
    question { id, translations { language, content { title } } }
  }
}
```

**Batch scoring:**

```graphql
mutation ScoreAnswersBatch(
  $userSurveyId: Int!
  $scores: [ScoreAnswerInput!]!
) {
  scoreAnswersBatch(
    userSurveyId: $userSurveyId
    scores: $scores
  ) {
    id
    score
  }
}

# Input type:
# ScoreAnswerInput { answerId: Int!, score: Int! }
```

**Validation:**
- Assessment must be submitted (`submitted_at` is set)
- All answer IDs must belong to the specified `userSurveyId`
- Can be called multiple times to update scores before evaluation

---

### Step 2: Trigger Evaluation

```graphql
mutation EvaluateManualAssessment(
  $userSurveyId: Int!
  $scoreOverride: Int           # optional — replaces aggregated score
  $actionIdOverride: Int        # optional — overrides score-range matched action
) {
  evaluateManualAssessment(
    userSurveyId: $userSurveyId
    scoreOverride: $scoreOverride
    actionIdOverride: $actionIdOverride
  ) {
    status            # "evaluated"
    score             # aggregated or overridden
    evaluatedAt       # ISO 8601 timestamp
    classifications {
      id
      count
      classification {
        id
        score
        translations { language, content { name } }
      }
    }
    recommendations {
      id
      count
      recommendation {
        id
        translations { language, content { description } }
      }
    }
  }
}
```

### What Happens Internally

1. **`evaluate_assessment()`** runs the standard pipeline:
   - Iterates all answers, computes per-answer scores from selected options
   - **Note:** If admin already set scores via `scoreAnswer`, those are overwritten by the pipeline's computed scores (based on selected option scores). For free-text questions with no options, the per-answer score stays as the admin set it.
   - Aggregates total score, classifications, recommendations
   - Matches action by score range
   - Sets `evaluated_at = now()`

2. **Overrides applied after aggregation:**
   - `scoreOverride` → replaces `user_survey.score` with the provided value
   - `actionIdOverride` → replaces the matched action with the specified `UserAction`

3. **Re-evaluation:** Can be called multiple times. Each call clears and rebuilds classifications and recommendations.

---

### Admin Scoring for Free-Text Questions

For question types without selectable options (text, textarea, number, file, date, time, datetime), the evaluation pipeline computes a score of 0. To assign scores to these answers:

1. Call `scoreAnswer` to set the score on each free-text answer
2. Call `evaluateManualAssessment` — the pipeline will compute 0 for these answers from options, but the admin-set scores are preserved for answers with no selected options

**Important:** For MCQ/grid answers, the pipeline always recomputes scores from the selected options' `score` values. Admin overrides on MCQ answers will be replaced during evaluation. Use `scoreOverride` on `evaluateManualAssessment` to override the final total instead.

---

## Frontend Integration

### Automatic Evaluation (User-Facing)

```javascript
async function submitAssessment(userSurveyId) {
  const { data } = await client.mutate({
    mutation: FINISH_ASSESSMENT,
    variables: { userSurveyId },
  });

  const result = data.finishAssessment;

  if (result.evaluatedAt) {
    // Auto-evaluated — show results immediately
    showResults({
      score: result.score,
      classifications: result.classifications,
      recommendations: result.recommendations,
    });
  }
}
```

### Manual Evaluation (Admin-Facing)

```javascript
// 1. Load submitted assessment with answers for review
const { data } = await client.query({
  query: GET_USER_SURVEY,
  variables: { userSurveyId },
});

const userSurvey = data.userSurvey;
// userSurvey.submittedAt is set, userSurvey.evaluatedAt is null

// 2. Display answers for admin review
for (const question of userSurvey.questions) {
  const answer = question.answers[0];
  // Show question title, user's answer, current score (if any)
}

// 3. Score individual answers
await client.mutate({
  mutation: SCORE_ANSWER,
  variables: {
    userSurveyId,
    answerId: answer.id,
    score: adminAssignedScore,
  },
});

// 4. Or batch score all at once
await client.mutate({
  mutation: SCORE_ANSWERS_BATCH,
  variables: {
    userSurveyId,
    scores: answers.map(a => ({
      answerId: a.id,
      score: a.adminScore,
    })),
  },
});

// 5. Trigger evaluation (with optional overrides)
const { data: evalData } = await client.mutate({
  mutation: EVALUATE_MANUAL_ASSESSMENT,
  variables: {
    userSurveyId,
    // scoreOverride: 85,        // optional
    // actionIdOverride: 7,      // optional
  },
});

// 6. Show results
const result = evalData.evaluateManualAssessment;
// result.status === "evaluated"
// result.score, result.classifications, result.recommendations
```

### Checking Evaluation Status

```javascript
// After submission, check if evaluation is pending
if (userSurvey.submittedAt && !userSurvey.evaluatedAt) {
  // Manual evaluation — show "Awaiting review" state
  showPendingReview();
} else if (userSurvey.evaluatedAt) {
  // Evaluated — show results
  // Note: classifications, recommendations, actions only return
  //        data when evaluatedAt is set
  showResults(userSurvey);
}
```

---

## Data Model Reference

### UserSurvey (evaluation fields)

| Field | Type | Description |
|-------|------|-------------|
| `is_evaluable` | bool | Whether evaluation is enabled |
| `evaluation_type` | string | `automatic_evaluation` or `manual_evaluation` |
| `use_score` | bool | Compute scores |
| `use_classifications` | bool | Aggregate classifications |
| `use_recommendations` | bool | Aggregate recommendations |
| `use_actions` | bool | Match score to action ranges |
| `score` | int / null | Total computed score |
| `action` | FK(UserAction) / null | Matched action |
| `evaluated_at` | datetime / null | When evaluation was performed |
| `submitted_at` | datetime / null | When assessment was submitted |

### UserAnswer (per-answer)

| Field | Type | Description |
|-------|------|-------------|
| `score` | int / null | Per-answer score (computed or admin-set) |
| `answer` | text / null | Free-text answer or option text |
| `selected_options` | M2M(UserAnswerOption) | Selected option references |
| `type` | string | Question type at time of answer |
| `answered_at` | datetime / null | When answered (anti-cheat) |
| `time_spent` | duration / null | Time since previous answer (anti-cheat) |

### UserAction (score ranges)

| Field | Type | Description |
|-------|------|-------------|
| `lower_limit` | float | Minimum score for this action |
| `upper_limit` | float | Maximum score for this action |
| `translations` | JSONB | `{lang: {title, description}}` |

### UserSurveyClassification (aggregated)

| Field | Type | Description |
|-------|------|-------------|
| `classification` | FK(UserClassification) | The classification |
| `count` | int | How many answers had this classification |

### UserSurveyRecommendation (aggregated)

| Field | Type | Description |
|-------|------|-------------|
| `recommendation` | FK(UserRecommendation) | The recommendation |
| `count` | int | How many answers triggered this recommendation |

---

## Submission Cleanup

When an assessment is submitted (both auto and manual), the system:

1. Validates all required questions are answered
2. Sets `submitted_at = now()`
3. **Deletes unanswered `UserQuestion` records** — only questions with actual answers are kept in the snapshot
4. Runs evaluation (automatic mode only)

This ensures the submitted snapshot only contains questions the user actually answered.

---

## GraphQL Schema Reference

### Mutations

```graphql
# Submit assessment (user)
mutation FinishAssessment($userSurveyId: Int!) {
  finishAssessment(userSurveyId: $userSurveyId) {
    status
    score
    evaluatedAt
    classifications { id, count, classification { id, translations { language, content { name } } } }
    recommendations { id, count, recommendation { id, translations { language, content { description } } } }
  }
}

# Score a single answer (admin)
mutation ScoreAnswer($userSurveyId: Int!, $answerId: Int!, $score: Int!) {
  scoreAnswer(userSurveyId: $userSurveyId, answerId: $answerId, score: $score) {
    id
    score
  }
}

# Score multiple answers (admin)
mutation ScoreAnswersBatch($userSurveyId: Int!, $scores: [ScoreAnswerInput!]!) {
  scoreAnswersBatch(userSurveyId: $userSurveyId, scores: $scores) {
    id
    score
  }
}

# Trigger manual evaluation (admin)
mutation EvaluateManualAssessment(
  $userSurveyId: Int!
  $scoreOverride: Int
  $actionIdOverride: Int
) {
  evaluateManualAssessment(
    userSurveyId: $userSurveyId
    scoreOverride: $scoreOverride
    actionIdOverride: $actionIdOverride
  ) {
    status
    score
    evaluatedAt
    classifications { id, count, classification { id, translations { language, content { name } } } }
    recommendations { id, count, recommendation { id, translations { language, content { description } } } }
  }
}
```
