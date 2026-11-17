/**
 * Strict TypeScript domain contracts for the EditVista Monograph Studio Cockpit.
 */

export type ViewportWidth = 1440 | 1024 | 768 | 390 | 360;

export interface ViewportPreset {
  readonly width: ViewportWidth;
  readonly label: string;
  readonly tag: string;
}

export interface DoDGates {
  readonly facts_verified: boolean;
  readonly rights_confirmed: boolean;
  readonly claim_scanner_passed: boolean;
  readonly five_view_qa_passed: boolean;
  readonly visual_critique_status: string;
  readonly section_hashes_present: boolean;
  readonly release_frozen: boolean;
  readonly archive_verified: boolean;
}

export interface StorageMetrics {
  readonly project_bytes: number;
  readonly max_project_bytes: number;
  readonly archive_exists: boolean;
  readonly archive_filename: string;
}

export interface DoDStatusResponse {
  readonly project_id: string;
  readonly status: string;
  readonly gates: DoDGates;
  readonly verified_fact_count: number;
  readonly total_fact_count: number;
  readonly confirmed_asset_count: number;
  readonly total_asset_count: number;
  readonly claim_violations: ReadonlyArray<string>;
  readonly section_hashes: Readonly<Record<string, string>>;
  readonly storage: StorageMetrics;
  readonly visual_defects: ReadonlyArray<Record<string, string>>;
}

export interface SectionInspectorResponse {
  readonly project_id: string;
  readonly section_name: string;
  readonly html: string;
  readonly sha256: string;
}

export interface GhlSimulationReport {
  readonly is_valid: boolean;
  readonly root_element_found: boolean;
  readonly unscoped_css_count: number;
  readonly global_leak_detected: boolean;
  readonly asset_urls_absolute: boolean;
}

export interface GhlExportResponse {
  readonly project_id: string;
  readonly root_id: string;
  readonly source_stage: string;
  readonly cdn_base_url: string;
  readonly ghl_html: string;
  readonly simulation: GhlSimulationReport;
}

export interface PruneResponse {
  readonly mode: string;
  readonly removable_count: number;
  readonly reclaimable_bytes: number;
  readonly deleted_count?: number;
  readonly deleted_files?: number;
  readonly reclaimed_bytes?: number;
  readonly archive?: string;
  readonly pre_approval?: boolean;
  readonly note?: string;
}

export type StageExecutionState = "pending" | "running" | "completed" | "failed" | "needs_review";

export interface PipelineStageItem {
  readonly step: number;
  readonly module: string;
  readonly title: string;
  readonly plain_title: string;
  readonly plain_analogy: string;
  readonly pdf_spec: string;
  readonly status: StageExecutionState;
  readonly evidence: string;
}

export interface ProjectStagesResponse {
  readonly project_id: string;
  readonly business_name: string;
  readonly primary_url: string;
  readonly project_status: string;
  readonly stages: ReadonlyArray<PipelineStageItem>;
}
