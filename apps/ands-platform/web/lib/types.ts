// Shapes returned by the journey BFF (apps/ands-platform/services/journey).

export interface Gate {
  reason: string;
  needs_key: string;
  needs_label: string;
  needs_route: string;
  requirement: string;
}

export interface Stage {
  n: number;
  key: string;
  label: string;
  reg: string;
  icon: string;
  purpose: string;
  unlocks: string;
  cta: string | null;
  next: string | null;
  checklist: string[];
  status: "done" | "current" | "locked";
  done: boolean;
  current: boolean;
  locked: boolean;
  gate: Gate | null;
  next_label: string | null;
  next_route: string | null;
}

export interface Position {
  current: number;
  current_key: string;
  current_label: string;
  done: number;
  total: number;
  percent: number;
  transmitted: boolean;
  complete: boolean;
  resume: { n: number; key: string; label: string; route: string };
}

export interface JourneySpine {
  id: string | null;
  title: string;
  dossier_id: string;
  stages: Stage[];
  current: number;
  position: Position;
}

export interface Tile {
  key: string;
  label: string;
  state: "pass" | "current" | "todo";
  reg: string;
}

export interface BlockingItem {
  key: string;
  label: string;
  requirement: string;
  route: string;
  why: string;
  cta: string | null;
}

export interface ReadinessCardData {
  status: "READY" | "BLOCKED";
  ready_to_file: boolean;
  transmitted: boolean;
  percent: number;
  done: number;
  total: number;
  tiles: Tile[];
  blocking_items: BlockingItem[];
  resume: { n: number; key: string; label: string; route: string };
}

export interface Advisory {
  rule: string;
  message: string;
}

export interface IntakeAssessment {
  route: {
    valid: boolean;
    submission_type?: string;
    label?: string;
    advice?: string;
    ands_content_model?: boolean;
    error?: string;
    content_model?: { modules: { module: string; title: string; required: boolean; suppressed: boolean }[] };
  };
  advisories: Advisory[];
  eligible_ands: boolean;
  checks: Record<string, any>;
}

export interface Slot {
  key: string;
  module: string;
  title: string;
  required: boolean;
  applicable: boolean;
  bilingual: boolean;
  state: "empty" | "partial" | "filled";
  doc: any;
  languages?: string[] | null;
}

export interface ModuleTower {
  module: string;
  state: "pass" | "partial" | "todo" | "na";
  required_total: number;
  required_filled: number;
}

export interface ContentView {
  slots: Slot[];
  progress: {
    required_total: number;
    required_filled: number;
    percent: number;
    complete: boolean;
    by_module: Record<string, { total: number; filled: number }>;
  };
  gate: { complete: boolean; missing: { key: string; title: string; module: string }[] };
  tower: ModuleTower[];
}

export interface Timer {
  notice: { type: string; date: string };
  due_date: string;
  days_remaining: number;
  overdue: boolean;
  paused: boolean;
  window_days: number;
  label: string;
  guidance: string;
}

export interface TrackSummary {
  phase: { phase: string; label: string; target_days: number | null; explanation: string };
  timers: Timer[];
  next_deadline: string | null;
  advisories: Advisory[];
}

export interface JourneyView {
  id: string;
  title: string;
  tenant_id: string;
  journey: JourneySpine;
  readiness: ReadinessCardData;
  content: ContentView;
  intake: IntakeAssessment | null;
  signals: Record<string, any>;
}

export interface Catalog {
  stages: Stage[];
  submission_types: Record<string, any>;
  be_rulesets: any[];
  dossier_branches: any[];
}
