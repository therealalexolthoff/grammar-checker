// Shapes returned by the API. The Python models in api/app/models.py and
// shared/schemas.py are the source of truth; these mirror them.

export type Answer = Record<string, string> | number[] | string;
export type Answers = Record<string, Answer>;

export type Blank = { id: string; accepted: string[] };

export type TeacherItem =
  | { id: string; type: "fill_blank"; text: string; blanks: Blank[]; concept: string; explanation: string }
  | { id: string; type: "reorder"; chunks: string[]; accepted_orders: string[][]; concept: string; explanation: string }
  | { id: string; type: "short_answer"; prompt: string };

export type Mark = "correct" | "partial" | "incorrect";

// An annotation as the API stores it: start/end are computed by the API.
export type Annotation = {
  code: string;
  span_text: string;
  occurrence: number;
  correction: string;
  explanation: string;
  start?: number;
  end?: number;
};

export type EvaluatedItem = { item_id: string; mark: Mark; feedback: string; annotations: Annotation[] };
export type Evaluation = { items: EvaluatedItem[] };
export type WritingEvaluation = { annotations: Annotation[]; comment: string };

export type Outcome = "fixed" | "unfixed" | "changed_wrongly";
// The student's revision as the teacher sees it. Keys are span indexes:
// positions in the evaluation's annotation list.
export type Revision = {
  edits: Record<string, string>;
  submitted_at: string | null;
  outcomes: Record<string, Outcome>;
  revised_text: string;
  changed: { index: string; start: number; end: number }[];
};

export type TeacherExercise = {
  exercise_id: string;
  student_id: string;
  kind: "grammar" | "writing";
  status: "draft" | "assigned";
  title: string;
  items: TeacherItem[]; // grammar only
  teacher_request: string;
  state: string;
  answers: Answers;
  grades: Record<string, boolean>;
  scrubbed_answers: Record<string, string>;
  evaluation: Evaluation | WritingEvaluation | null;
  evaluation_valid: boolean;
  // Writing only:
  prompt?: string;
  min_words?: number | null;
  max_words?: number | null;
  photo_count?: number;
  transcription?: string | null;
  final_source?: "typed" | "photo" | null;
  revision?: Revision | null;
};

export type ExerciseSummary = { exercise_id: string; title: string; status?: string; state: string };
export type Student = { student_id: string; username: string; active: boolean };
export type Code = { code: string; description: string };

export type StudentItem = {
  id: string;
  type: "fill_blank" | "reorder" | "short_answer";
  text?: string;
  blank_ids?: string[];
  chunks?: string[];
  prompt?: string;
  correct?: boolean;
  correct_answer?: Record<string, string> | string[];
  explanation?: string;
  // Short answers, after release:
  mark?: Mark;
  feedback?: string;
  answer_text?: string;
  spans?: StudentSpan[];
};

export type StudentSpan = { start: number; end: number; code: string; meaning: string };

export type StudentExercise = {
  exercise_id: string;
  kind: "grammar" | "writing";
  title: string;
  state: string;
  answers: Answers;
  items: StudentItem[]; // grammar only
  // Writing only:
  prompt?: string;
  min_words?: number;
  max_words?: number;
  // Writing, after release:
  answer_text?: string;
  spans?: StudentSpan[]; // in annotation order: revision edits refer to these positions
  comment?: string;
  revision_edits?: Record<string, string>;
  revised_text?: string;
  // Writing, once the teacher sends back the checked revision:
  outcomes?: Record<string, Outcome>; // only spans the student changed
  corrections?: Record<string, string>; // only spans not fixed
};

// ---- Phase 7: profile, lessons, overview ----

export type ProfileRow = {
  code: string;
  meaning: string;
  errors: number;
  fixed: number;
  unfixed: number;
  changed_wrongly: number;
};
export type StudentProfile = {
  profile: { window: number; submissions_counted: number; codes: ProfileRow[] };
  teacher_notes: string;
};

export type LessonExample = { incorrect: string; correct: string; note: string };
export type TeacherLesson = {
  lesson_id: string;
  student_id: string;
  status: "draft" | "assigned";
  request: string;
  title: string;
  explanation: string;
  examples: LessonExample[];
  word_count: number;
  read_at: string | null;
};
export type LessonSummary = { lesson_id: string; title: string; status: string; read_at: string | null };
export type StudentLesson = { lesson_id: string; title: string; explanation: string; examples: LessonExample[]; read: boolean };
export type StudentLessonSummary = { lesson_id: string; title: string; read: boolean };

export type OverviewRow = {
  student_id: string;
  username: string;
  work: { exercise_id: string; title: string; state: string }[];
  unread_lessons: { lesson_id: string; title: string }[];
};
