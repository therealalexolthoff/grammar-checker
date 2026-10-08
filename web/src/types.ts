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

export type TeacherExercise = {
  exercise_id: string;
  student_id: string;
  status: "draft" | "assigned";
  title: string;
  items: TeacherItem[];
  teacher_request: string;
  state: string;
  answers: Answers;
  grades: Record<string, boolean>;
  scrubbed_answers: Record<string, string>;
  evaluation: Evaluation | null;
  evaluation_valid: boolean;
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
  spans?: { start: number; end: number; code: string; meaning: string }[];
};

export type StudentExercise = {
  exercise_id: string;
  title: string;
  state: string;
  answers: Answers;
  items: StudentItem[];
};
