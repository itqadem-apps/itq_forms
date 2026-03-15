# Results Page — Frontend Specification

## Overview

The results page displays after an assessment is submitted. Its content adapts based on evaluation state, survey configuration flags, and survey type. This document defines every section, its visibility conditions, and the data it renders.

---

## Page States

The results page has three possible states, determined by two fields:

| State | `submittedAt` | `evaluatedAt` | When |
|-------|--------------|---------------|------|
| **Not submitted** | `null` | `null` | User hasn't finished — redirect back to survey |
| **Pending review** | set | `null` | Manual evaluation — submitted but not yet reviewed by admin |
| **Evaluated** | set | set | Results are ready (auto or manual) |

```javascript
if (!userSurvey.submittedAt) {
  redirect("/survey/" + userSurvey.id);
} else if (!userSurvey.evaluatedAt) {
  renderPendingReview();
} else {
  renderResults();
}
```

---

## Page Layout

```
┌─────────────────────────────────────────────┐
│  HEADER                                     │
│  Survey title, type badge, child info       │
├─────────────────────────────────────────────┤
│  STATUS BANNER                              │
│  Evaluated / Pending Review / Time's Up     │
├─────────────────────────────────────────────┤
│  SCORE CARD               (if use_score)    │
│  Total score, action feedback               │
├─────────────────────────────────────────────┤
│  CLASSIFICATIONS          (if use_classif.) │
│  Ranked list with counts                    │
├─────────────────────────────────────────────┤
│  RECOMMENDATIONS          (if use_recom.)   │
│  List of recommendation cards               │
├─────────────────────────────────────────────┤
│  ANSWER REVIEW                              │
│  Per-question breakdown with scores         │
├─────────────────────────────────────────────┤
│  SUMMARY STATS                              │
│  Time taken, questions answered, etc.       │
├─────────────────────────────────────────────┤
│  FOOTER ACTIONS                             │
│  Retake / Back to dashboard                 │
└─────────────────────────────────────────────┘
```

---

## Section Details

### 1. Header

**Always visible.**

| Element | Source | Notes |
|---------|--------|-------|
| Survey title | `translations[lang].content.title` | Use current language, fallback to primary |
| Survey description | `translations[lang].content.description` | Optional, below title |
| Type badge | `surveyType` | "Exam", "Questionnaire", "Survey", etc. |
| Child name | `child.name` | Only when `isForChild === true` |
| Child photo | `child.photoId` | Only when `isForChild === true` and photo exists |

---

### 2. Status Banner

**Always visible.** Style and content depend on page state.

#### State: Evaluated

| `terminationReason` | Banner |
|---------------------|--------|
| `completed` | "Your results are ready" — success/green style |
| `time_expired` | "Time expired — your assessment was auto-submitted" — warning/amber style |
| `ending_option` | "Assessment ended early based on your responses" — info/blue style |

#### State: Pending Review

| Condition | Banner |
|-----------|--------|
| `evaluatedAt` is null | "Your assessment has been submitted and is awaiting review" — info/blue style |
| `evaluationType === "manual_evaluation"` | Append: "An evaluator will review your answers" |

#### Termination Reason Values

| Value | Meaning | Set by |
|-------|---------|--------|
| `completed` | User clicked submit | `finishAssessment` mutation |
| `time_expired` | Timer ran out | `answerQuestion`, `shouldTerminate`, `auto_submit_expired` cron |
| `ending_option` | Ending-option threshold reached | `shouldTerminate` query |

**When pending:** Hide all result sections (score, classifications, recommendations, answer scores). Only show the header, status banner, answer review (without scores), and summary stats.

---

### 3. Score Card

**Visible when:** `evaluatedAt !== null && useScore === true`

| Element | Source | Condition |
|---------|--------|-----------|
| Total score | `score` | Always in this section |
| Score label | "Total Score" or "Your Score" | — |
| Max possible score | Compute from questions' max option scores | Optional — sum of highest-scoring option per question |
| Score percentage | `score / maxScore * 100` | Optional — show as circular progress or bar |
| Action title | `actions[matched].translations[lang].content.title` | Only when `useActions === true && actionId !== null` |
| Action description | `actions[matched].translations[lang].content.description` | Only when `useActions === true && actionId !== null` |

**Finding the matched action:**
```javascript
// actionId is on the userSurvey
const matchedAction = userSurvey.actions.find(a => a.id === userSurvey.actionId);
```

**Display variants by survey type:**

| `surveyType` | Suggested display |
|--------------|-------------------|
| `exam` | Score as fraction (e.g. "24 / 30") with pass/fail styling |
| `questionnaire` | Score as percentage with progress ring |
| `survey` | Simple numeric display |
| `smart_form` | Action feedback card (title + description) prominently |
| `curriculum` | Score with completion badge |

---

### 4. Classifications

**Visible when:** `evaluatedAt !== null && useClassifications === true && surveyClassifications.length > 0`

Data source: `userSurvey.surveyClassifications` (sorted by count descending from server).

| Element | Source |
|---------|--------|
| Classification name | `classification.translations[lang].content.name` |
| Count | `count` |
| Rank | Index position (1st = dominant) |

**Display:** Ranked list or bar chart. The first classification is the "primary result".

```
┌─────────────────────────────────────┐
│  Your Profile                       │
│                                     │
│  1. Analytical ██████████████  4    │
│  2. Creative   ████████       2    │
│  3. Social     ████           1    │
└─────────────────────────────────────┘
```

**Variant — Single dominant classification:**
If only showing the primary result, display the first item as a large card with its name. Show the rest as secondary.

---

### 5. Recommendations

**Visible when:** `evaluatedAt !== null && useRecommendations === true && surveyRecommendations.length > 0`

Data source: `userSurvey.surveyRecommendations` (sorted by count descending from server).

| Element | Source |
|---------|--------|
| Description | `recommendation.translations[lang].content.description` |
| Count | `count` (how many answers triggered this) |

**Display:** Card list. Each recommendation is a card with the description text. Optionally show the count as a relevance indicator.

```
┌─────────────────────────────────────┐
│  Recommendations                    │
│                                     │
│  ┌───────────────────────────────┐  │
│  │ Consider data science courses │  │
│  │ Based on 3 of your answers   │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │ Try creative workshops        │  │
│  │ Based on 1 of your answers   │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

---

### 6. Answer Review

**Always visible** (both pending and evaluated states). Shows all questions with the user's answers.

**Data source:** `userSurvey.questions` — after submission, only answered questions remain (unanswered are deleted).

Each question displays:

| Element | Source | Condition |
|---------|--------|-----------|
| Question number | Index in ordered list | Always |
| Question title | `question.translations[lang].content.title` | Always |
| Question description | `question.translations[lang].content.description` | If exists |
| Question type badge | `question.type` | Optional |
| User's answer | See answer display by type below | Always |
| Answer score | `question.answers[0].score` | Only when `evaluatedAt !== null && useScore === true` |
| Correct indicator | Compare answer score to max option score | Optional — see below |
| Time spent | `question.answers[0].timeSpent` | Only when `enableAntiCheat === true` |

#### Answer Display by Question Type

**Radio / Dropdown (single-select):**
```
Selected: ● Option text
Score: 10/10 ✓
```
Show the selected option. Optionally show all options with the selected one highlighted and correct one marked (for exams).

**Checkbox (multi-select):**
```
Selected: ☑ Option A, ☑ Option C
Score: 10/15
```
Show all selected options as chips or a comma-separated list.

**Text / Textarea:**
```
Answer: "The user's typed response here..."
Score: 8 (admin-assigned)
```
Show the free-text answer in a read-only styled box.

**Number:**
```
Answer: 42
```

**File:**
```
📎 portfolio.pdf
```
Show file name with icon. Link to download if available.

**Date:**
```
Answer: March 15, 2026
```
Format using locale-appropriate date format.

**Time:**
```
Answer: 2:30 PM
```

**DateTime:**
```
Answer: March 15, 2026 at 2:30 PM
```

**Radio Grid:**
```
┌──────────┬──────────┐
│ Math     │ Good     │
│ Science  │ Excellent│
│ English  │ Fair     │
└──────────┴──────────┘
Score: 20/30
```
Show each row with its selected column value.

**Checkbox Grid:**
```
┌──────────┬─────────────────────┐
│ Frontend │ JavaScript, Docker  │
│ Backend  │ Python              │
│ DevOps   │ Docker, Python      │
└──────────┴─────────────────────┘
Score: 8/12
```
Show each row with all selected column values.

#### Correct/Incorrect Indicators (Exam Mode)

**Visible when:** `surveyType === "exam" && evaluatedAt !== null && useScore === true`

For MCQ questions, determine correctness:

```javascript
const maxScore = Math.max(...question.answerSchema.options.map(o => o.score || 0));
const userScore = question.answers[0]?.score || 0;
const isCorrect = userScore === maxScore;
const isPartial = userScore > 0 && userScore < maxScore; // checkbox
```

| Indicator | Condition | Style |
|-----------|-----------|-------|
| Correct | `userScore === maxScore` | Green check, green left-border |
| Partial | `userScore > 0 && userScore < maxScore` | Yellow/amber, partial icon |
| Incorrect | `userScore === 0` | Red cross, red left-border |
| Not scored | `score === null` | Gray, no indicator |

**Optional — Show correct answer:** For exams, show which option had the highest score:

```javascript
const correctOption = question.answerSchema.options
  .filter(o => !o.isRow && !o.isColumn)
  .reduce((best, o) => (o.score || 0) > (best.score || 0) ? o : best);
```

---

### 7. Summary Stats

**Always visible.**

| Stat | Source | Condition |
|------|--------|-----------|
| Submitted at | `submittedAt` | Always — format as locale date+time |
| Total questions | `questions.length` | Always |
| Total answered | `questions.length` (all remaining are answered) | Always |
| Time taken | `submittedAt - startedAt` | Only when `startedAt !== null` |
| Time limit | `timeLimit` | Only when `isTimed === true` |
| Time remaining | `timeLimit - (submittedAt - startedAt)` | Only when `isTimed === true` and didn't expire |
| Tab switches | `tabSwitchCount` | Only when `enableAntiCheat === true && tabSwitchCount > 0` |

**Time display:**
```javascript
const timeTaken = new Date(submittedAt) - new Date(startedAt);
const minutes = Math.floor(timeTaken / 60000);
const seconds = Math.floor((timeTaken % 60000) / 1000);
// "12 min 34 sec"
```

---

### 8. Footer Actions

**Always visible.**

| Action | Condition | Behavior |
|--------|-----------|----------|
| "Back to Dashboard" | Always | Navigate to survey list or collection page |
| "Retake Assessment" | `usageUsed < usageLimit` | Navigate to enrollment for the same survey |
| "View Collection" | `collectionId !== null` | Navigate to collection page |
| "Print Results" | `evaluatedAt !== null` | Trigger browser print or export |

**Retake logic:**
```javascript
const canRetake = userSurvey.usageUsed < userSurvey.usageLimit;
```

---

## Conditional Visibility Matrix

| Section | Not Submitted | Pending Review | Evaluated |
|---------|:---:|:---:|:---:|
| Header | redirect | show | show |
| Status Banner | — | "Awaiting review" | "Results ready" |
| Score Card | — | hide | show if `useScore` |
| Classifications | — | hide | show if `useClassifications` + has data |
| Recommendations | — | hide | show if `useRecommendations` + has data |
| Answer Review | — | show (no scores) | show (with scores) |
| Correct Indicators | — | hide | show if `exam` + `useScore` |
| Summary Stats | — | show | show |
| Footer Actions | — | show | show |

---

## GraphQL Query

```graphql
query GetResults($userSurveyId: Int!) {
  userSurvey(id: $userSurveyId) {
    id
    surveyId
    surveyType
    displayOption
    isTimed
    timeLimit
    isForChild
    isEvaluable
    evaluationType
    useScore
    useClassifications
    useRecommendations
    useActions
    enableAntiCheat
    coverId

    # state
    startedAt
    submittedAt
    evaluatedAt
    terminationReason
    score
    actionId
    tabSwitchCount

    # usage
    usageUsed
    usageLimit

    # child
    child {
      id
      name
      photoId
    }

    # translations
    translations {
      language
      content {
        title
        description
        shortDescription
      }
    }

    # classifications (empty array if not evaluated)
    surveyClassifications {
      id
      count
      classification {
        id
        score
        translations {
          language
          content { name }
        }
      }
    }

    # recommendations (empty array if not evaluated)
    surveyRecommendations {
      id
      count
      recommendation {
        id
        translations {
          language
          content { description }
        }
      }
    }

    # actions (empty array if not evaluated)
    actions {
      id
      upperLimit
      lowerLimit
      translations {
        language
        content { title, description }
      }
    }

    # questions with answers
    questions {
      id
      type
      order
      isRequired
      coverAssetId
      translations {
        language
        content { title, description }
      }
      answerSchema {
        id
        type
        isMcq
        isGrid
        options {
          id
          score
          isRow
          isColumn
          order
          translations {
            language
            content { text }
          }
        }
      }
      answers {
        id
        answer
        score
        type
        timeSpent
        answeredAt
        selectedOptions {
          id
          score
          isRow
          isColumn
          translations {
            language
            content { text }
          }
        }
      }
    }
  }
}
```

---

## Rendering Logic Pseudocode

```javascript
function ResultsPage({ userSurveyId }) {
  const { data } = useQuery(GET_RESULTS, { variables: { userSurveyId } });
  const survey = data.userSurvey;
  const lang = getCurrentLanguage();
  const t = (translations) => getTranslation(translations, lang);

  // ── State check ──
  if (!survey.submittedAt) return <Redirect to={`/survey/${survey.id}`} />;

  const isEvaluated = !!survey.evaluatedAt;
  const isPending = survey.submittedAt && !survey.evaluatedAt;
  const isExam = survey.surveyType === "exam";
  const reason = survey.terminationReason; // "completed" | "time_expired" | "ending_option"

  // ── Matched action ──
  const matchedAction = survey.useActions && survey.actionId
    ? survey.actions.find(a => a.id === survey.actionId)
    : null;

  // ── Max possible score ──
  const maxScore = survey.useScore
    ? survey.questions.reduce((sum, q) => {
        if (!q.answerSchema) return sum;
        const opts = q.answerSchema.options.filter(o => !o.isRow);
        if (q.answerSchema.isMcq) {
          // Single select: max single option; Multi select: sum of positive scores
          if (q.type === "checkbox") {
            return sum + opts.reduce((s, o) => s + Math.max(o.score || 0, 0), 0);
          }
          return sum + Math.max(...opts.map(o => o.score || 0), 0);
        }
        if (q.answerSchema.isGrid) {
          const cols = opts.filter(o => o.isColumn);
          const rows = opts.filter(o => o.isRow);
          const maxCol = Math.max(...cols.map(o => o.score || 0), 0);
          return sum + (rows.length * maxCol);
        }
        return sum;
      }, 0)
    : null;

  return (
    <Page>
      {/* 1. Header */}
      <Header
        title={t(survey.translations)?.title}
        description={t(survey.translations)?.description}
        surveyType={survey.surveyType}
        child={survey.isForChild ? survey.child : null}
      />

      {/* 2. Status Banner */}
      {isPending && <Banner type="info" text="Awaiting review" />}
      {isEvaluated && reason === "completed" && <Banner type="success" text="Results ready" />}
      {isEvaluated && reason === "time_expired" && <Banner type="warning" text="Time expired — auto-submitted" />}
      {isEvaluated && reason === "ending_option" && <Banner type="info" text="Assessment ended early based on your responses" />}

      {/* 3. Score Card — only when evaluated + useScore */}
      {isEvaluated && survey.useScore && (
        <ScoreCard
          score={survey.score}
          maxScore={maxScore}
          action={matchedAction}
          surveyType={survey.surveyType}
          lang={lang}
        />
      )}

      {/* 4. Classifications — only when evaluated + has data */}
      {isEvaluated && survey.useClassifications
        && survey.surveyClassifications.length > 0 && (
        <Classifications
          items={survey.surveyClassifications}
          lang={lang}
        />
      )}

      {/* 5. Recommendations — only when evaluated + has data */}
      {isEvaluated && survey.useRecommendations
        && survey.surveyRecommendations.length > 0 && (
        <Recommendations
          items={survey.surveyRecommendations}
          lang={lang}
        />
      )}

      {/* 6. Answer Review — always (scores shown only when evaluated) */}
      <AnswerReview
        questions={survey.questions}
        showScores={isEvaluated && survey.useScore}
        showCorrectAnswers={isEvaluated && isExam && survey.useScore}
        showTimeSpent={survey.enableAntiCheat}
        lang={lang}
      />

      {/* 7. Summary Stats */}
      <SummaryStats
        submittedAt={survey.submittedAt}
        startedAt={survey.startedAt}
        isTimed={survey.isTimed}
        timeLimit={survey.timeLimit}
        questionCount={survey.questions.length}
        tabSwitchCount={survey.enableAntiCheat ? survey.tabSwitchCount : null}
      />

      {/* 8. Footer */}
      <Footer
        canRetake={survey.usageUsed < survey.usageLimit}
        surveyId={survey.surveyId}
        collectionId={survey.collectionId}
        canPrint={isEvaluated}
      />
    </Page>
  );
}
```

---

## RTL Support

When the survey language is RTL (e.g. Arabic):
- Mirror the entire layout direction
- Right-align text and labels
- Flip progress bars and charts
- Use `dir="rtl"` on the page container

Detect from survey language:
```javascript
const rtlLanguages = ["ar", "he", "fa", "ur"];
const isRTL = rtlLanguages.includes(survey.translations[0]?.language);
```

---

## Edge Cases

| Case | Handling |
|------|----------|
| No questions answered (early termination) | Show empty answer review with message: "No questions were answered" |
| All scores are 0 | Show score as "0 / {max}" — don't hide |
| No classifications returned | Hide classifications section entirely |
| No recommendations returned | Hide recommendations section entirely |
| No action matched (score outside all ranges) | Hide action from score card |
| `useScore=false` but `useClassifications=true` | Show classifications without score card |
| `isEvaluable=false` | Show only answer review and summary — no score/classification/recommendation sections |
| Manual evaluation re-evaluated | Show latest results (query returns current state) |
| Survey has no sections (orphaned questions) | Should not happen — filtered out during evaluation |
