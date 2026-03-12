# Anti-Cheating System

## Overview

The anti-cheating system protects timed assessments and exams through 8 layered defenses. All anti-cheat features are controlled by a **master toggle** (`enable_anti_cheat`) on the survey. When disabled, none of the anti-cheat logic runs (session tokens, tab tracking, IP logging, answer locking, etc.). Time enforcement (`is_timed` + `time_limit`) is always active regardless of the toggle.

---

## Survey Configuration Fields

| Field                  | Type    | Default | Description                                      |
|------------------------|---------|---------|--------------------------------------------------|
| **`enable_anti_cheat`**| bool    | false   | **Master toggle** - enables all anti-cheat features |
| `is_timed`             | bool    | false   | Enable time-limited assessments (always enforced) |
| `time_limit`           | duration| null    | Max duration (e.g. `"0:30:00"` for 30 min)       |
| `lock_answers`         | bool    | false   | Prevent changing already-answered questions       |
| `randomize_questions`  | bool    | false   | Shuffle question order per enrollment             |
| `randomize_options`    | bool    | false   | Shuffle answer option order per enrollment        |
| `allow_end_based_on_answer_repeat` | bool | false | Enable ending-option termination logic |
| `answers_count_to_end` | int     | 0       | Threshold for ending-option counter               |

### What `enable_anti_cheat` controls

| Feature                        | Requires `enable_anti_cheat` | Notes                              |
|--------------------------------|-----------------------------|------------------------------------|
| Session token validation       | Yes                         | Token not generated when off       |
| Heartbeat session check        | Yes                         | Returns `true` silently when off   |
| Lock answers                   | Yes                         | Also requires `lock_answers=true`  |
| Tab switch tracking            | Yes                         | Events silently ignored when off   |
| Answer speed tracking          | Yes                         | `answered_at`/`time_spent` not set |
| IP / user-agent logging        | Yes                         | Not recorded when off              |
| Randomization                  | No                          | Controlled by own flags            |
| Time enforcement               | No                          | Always active for timed surveys    |
| Ending-option termination      | No                          | Controlled by own flags            |

---

## Features

### 1. Server-Side Time Enforcement

The server rejects any answer submitted after `started_at + time_limit`. The timer starts on the first answer, not on enrollment.

**Flow:**
1. User submits first answer -> `started_at` is set to `now()`
2. On every subsequent answer -> server checks `now() - started_at >= time_limit`
3. If expired -> auto-submits the assessment and returns an error

**No client-side timer can be trusted.** The server is the single source of truth.

### 2. Single Active Session

A `session_token` (UUID4) is generated at enrollment. The frontend must store it and send it with every `answerQuestion` call. If the token doesn't match (e.g. exam opened in another tab), the request is rejected.

**GraphQL mutations:**

```graphql
# Returns sessionToken on enrollment
mutation {
  enrollAssessment(surveyId: 1) {
    id
    sessionToken
  }
}

# Heartbeat - call every 30 seconds
mutation {
  heartbeat(userSurveyId: 1, sessionToken: "uuid-here")
}

# Answer - include session token
mutation {
  answerQuestion(
    userSurveyId: 1
    questionId: 5
    answer: ["42"]
    sessionToken: "uuid-here"
  ) {
    id
  }
}
```

### 3. Lock Answered Questions

When `lock_answers` is enabled, a question can only be answered once. Attempting to change an existing answer returns:

```
"This question has already been answered and cannot be changed."
```

### 4. Question & Option Randomization

When enabled, the `order` field is shuffled during enrollment snapshot creation. Each user gets a permanently stored random order. Since ordering is baked into the snapshot, no runtime randomization is needed.

- `randomize_questions` - shuffles question presentation order
- `randomize_options` - shuffles answer option order within each question

### 5. Tab Switch / Focus Loss Tracking

Every time the user leaves the exam tab, the frontend reports it. The backend stores each event and maintains a counter.

**GraphQL mutation:**

```graphql
mutation {
  reportTabSwitch(userSurveyId: 1, eventType: "visibility_hidden")
}
```

**Event types to report:**
- `visibility_hidden` - document.visibilitychange fired with `document.hidden === true`
- `blur` - window lost focus

The `tab_switch_count` field on `UserSurveyType` exposes the total count.

### 6. Answer Speed Tracking

Each answer records:
- `answered_at` - timestamp when the answer was submitted
- `time_spent` - duration since the previous answer (or since `started_at` for the first answer)

Abnormally fast answers (e.g. < 2 seconds) can be flagged in admin review.

### 7. IP & User-Agent Tracking

Each answer silently records:
- `ip_address` - client IP (supports `X-Forwarded-For` for reverse proxies)
- `user_agent` - browser user-agent string

These fields are **not exposed in the GraphQL API** (admin/DB only). Useful for detecting:
- Device switching mid-exam
- Multiple people taking the same exam from different locations

### 8. Auto-Submit on Time Expiry

Two mechanisms ensure expired exams are always finalized:

**Lazy (on interaction):**
- `shouldTerminate` query auto-submits when it detects time expiry
- `answerQuestion` mutation auto-submits before returning the error

**Proactive (cron job):**
```bash
# Run every minute to catch abandoned sessions
* * * * * cd /path/to/project && .venv/bin/python manage.py auto_submit_expired
```

---

## Frontend Integration

### Setup (on enrollment)

```javascript
const { data } = await client.mutate({
  mutation: ENROLL_ASSESSMENT,
  variables: { surveyId, childId, collectionId },
});

const userSurvey = data.enrollAssessment;

// Persist for the exam session
sessionStorage.setItem("userSurveyId", userSurvey.id);
sessionStorage.setItem("enableAntiCheat", userSurvey.enableAntiCheat);

if (userSurvey.enableAntiCheat && userSurvey.sessionToken) {
  sessionStorage.setItem("examSessionToken", userSurvey.sessionToken);
}
```

### Answering Questions

```javascript
const antiCheat = sessionStorage.getItem("enableAntiCheat") === "true";
const sessionToken = antiCheat
  ? sessionStorage.getItem("examSessionToken")
  : null;

const { data } = await client.mutate({
  mutation: ANSWER_QUESTION,
  variables: {
    userSurveyId: parseInt(sessionStorage.getItem("userSurveyId")),
    questionId,
    answer: [selectedOptionId.toString()],
    sessionToken, // null when anti-cheat is off — server ignores it
  },
});

// Check for time expiry or session conflict errors
// and redirect to results page if needed
```

### Heartbeat (every 30 seconds)

```javascript
let heartbeatInterval;

function startHeartbeat(userSurveyId, sessionToken) {
  heartbeatInterval = setInterval(async () => {
    try {
      await client.mutate({
        mutation: HEARTBEAT,
        variables: { userSurveyId, sessionToken },
      });
    } catch (err) {
      if (err.message.includes("Session conflict")) {
        stopHeartbeat();
        // Show "exam open in another window" overlay
        // Lock all UI interactions
      }
    }
  }, 30000);
}

function stopHeartbeat() {
  clearInterval(heartbeatInterval);
}
```

### Termination Polling (every 10 seconds)

```javascript
let terminationInterval;

function startTerminationCheck(userSurveyId) {
  terminationInterval = setInterval(async () => {
    const { data } = await client.query({
      query: SHOULD_TERMINATE,
      variables: { userSurveyId },
      fetchPolicy: "network-only",
    });

    if (data.shouldTerminate) {
      stopTerminationCheck();
      stopHeartbeat();
      // Navigate to results / "time's up" screen
    }
  }, 10000);
}

function stopTerminationCheck() {
  clearInterval(terminationInterval);
}
```

### Tab Switch Detection

```javascript
function startTabSwitchDetection(userSurveyId) {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      client.mutate({
        mutation: REPORT_TAB_SWITCH,
        variables: { userSurveyId, eventType: "visibility_hidden" },
      });
    }
  });

  window.addEventListener("blur", () => {
    client.mutate({
      mutation: REPORT_TAB_SWITCH,
      variables: { userSurveyId, eventType: "blur" },
    });
  });
}
```

### UI Lockdown (optional)

```javascript
function lockdownUI() {
  // Disable right-click
  document.addEventListener("contextmenu", (e) => e.preventDefault());

  // Disable copy/paste
  document.addEventListener("copy", (e) => e.preventDefault());
  document.addEventListener("paste", (e) => e.preventDefault());

  // Block keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    const blocked =
      (e.ctrlKey && ["c", "v", "u", "a"].includes(e.key.toLowerCase())) ||
      e.key === "F12" ||
      (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "i");
    if (blocked) e.preventDefault();
  });

  // Disable text selection via CSS
  document.body.style.userSelect = "none";
  document.body.style.webkitUserSelect = "none";
}
```

### Complete Exam Lifecycle

```javascript
async function startExam(surveyId) {
  // 1. Enroll
  const userSurvey = await enrollAssessment(surveyId);
  const { id: userSurveyId, sessionToken, enableAntiCheat, isTimed } =
    userSurvey;

  // 2. Store session
  sessionStorage.setItem("userSurveyId", userSurveyId);
  sessionStorage.setItem("enableAntiCheat", enableAntiCheat);

  // 3. Start termination check (always needed for timed surveys)
  if (isTimed) {
    startTerminationCheck(userSurveyId);
  }

  // 4. Start anti-cheat monitors (only when enabled)
  if (enableAntiCheat) {
    sessionStorage.setItem("examSessionToken", sessionToken);
    startHeartbeat(userSurveyId, sessionToken);
    startTabSwitchDetection(userSurveyId);
    lockdownUI();
  }

  // 5. Load first question and begin exam...
}

async function endExam() {
  stopHeartbeat();
  stopTerminationCheck();

  await client.mutate({
    mutation: FINISH_ASSESSMENT,
    variables: {
      userSurveyId: parseInt(sessionStorage.getItem("userSurveyId")),
    },
  });

  sessionStorage.removeItem("examSessionToken");
  sessionStorage.removeItem("userSurveyId");
  sessionStorage.removeItem("enableAntiCheat");

  // Navigate to results
}
```

---

## GraphQL Schema Reference

### Queries

```graphql
# Check if the assessment should be terminated
query ShouldTerminate($userSurveyId: Int!) {
  shouldTerminate(userSurveyId: $userSurveyId)
}
```

### Mutations

```graphql
mutation EnrollAssessment($surveyId: Int!, $childId: String, $collectionId: Int) {
  enrollAssessment(surveyId: $surveyId, childId: $childId, collectionId: $collectionId) {
    id
    enableAntiCheat
    sessionToken
    isTimed
    timeLimit
    lockAnswers
    randomizeQuestions
    randomizeOptions
  }
}

mutation AnswerQuestion(
  $userSurveyId: Int!
  $questionId: Int!
  $answer: [String!]!
  $sessionToken: String
) {
  answerQuestion(
    userSurveyId: $userSurveyId
    questionId: $questionId
    answer: $answer
    sessionToken: $sessionToken
  ) {
    id
    answeredAt
    timeSpent
  }
}

mutation Heartbeat($userSurveyId: Int!, $sessionToken: String!) {
  heartbeat(userSurveyId: $userSurveyId, sessionToken: $sessionToken)
}

mutation ReportTabSwitch($userSurveyId: Int!, $eventType: String!) {
  reportTabSwitch(userSurveyId: $userSurveyId, eventType: $eventType)
}

mutation FinishAssessment($userSurveyId: Int!) {
  finishAssessment(userSurveyId: $userSurveyId) {
    status
    score
    evaluatedAt
  }
}
```

---

## Cron Job Setup

```bash
# Add to crontab (crontab -e)
* * * * * cd /path/to/itq_forms && .venv/bin/python manage.py auto_submit_expired >> /var/log/auto_submit.log 2>&1
```

---

## Admin Review Checklist

When reviewing an exam submission, check:

1. **`tab_switch_count`** - High numbers indicate frequent tab switching
2. **`time_spent` per answer** - Suspiciously fast answers (< 2s) may indicate pre-knowledge
3. **`ip_address` changes** - Different IPs across answers suggest device switching
4. **`user_agent` changes** - Different browsers/devices mid-exam
5. **`started_at` vs `submitted_at`** - Total exam duration vs expected time
