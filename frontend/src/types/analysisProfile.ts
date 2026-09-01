export type AnalysisProfileStatus = 'draft' | 'published' | 'deprecated'
export type AnalysisAnalyst = 'market' | 'fundamentals' | 'news' | 'social'
export type AnalysisResearchDepth = '快速' | '基础' | '标准' | '深度' | '全面'
export type AnalysisRiskPreference = 'conservative' | 'balanced' | 'aggressive'
export type AnalysisInvestmentHorizon = 'short' | 'medium' | 'long'

export interface AnalysisModelReference {
  config_id: string
  model_name: string | null
}

export interface AnalysisFactorContext {
  factor_ids: string[]
  summary_schema_version: string
  max_evidence_items_per_factor: number
}

export interface AnalysisProfile {
  profile_id: string
  user_id: string
  name: string
  current_draft_version_id: string | null
  latest_published_version_id: string | null
  version_sequence: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface AnalysisProfileVersion {
  profile_version_id: string
  profile_id: string
  user_id: string
  version: number
  status: AnalysisProfileStatus
  selected_analysts: AnalysisAnalyst[]
  research_depth: AnalysisResearchDepth
  quick_model_ref: AnalysisModelReference
  deep_model_ref: AnalysisModelReference
  risk_preference: AnalysisRiskPreference
  investment_horizon: AnalysisInvestmentHorizon
  enabled_skill_versions: string[]
  factor_context: AnalysisFactorContext
  strategy_context: string | null
  debate_rounds: number
  risk_debate_rounds: number
  output_schema_version: string
  disclaimer_profile: string
  checksum: string | null
  created_at: string
  created_by: string
  published_at: string | null
  change_summary: string
  parent_version_id: string | null
}

export interface AnalysisProfilePair {
  profile: AnalysisProfile
  version: AnalysisProfileVersion
}

export interface AnalysisProfileDetail {
  profile: AnalysisProfile
  versions: AnalysisProfileVersion[]
}

export interface AnalysisProfilePage {
  items: AnalysisProfile[]
  page: number
  page_size: number
  total: number
}

export interface AnalysisProfileForm {
  name: string
  selected_analysts: AnalysisAnalyst[]
  research_depth: AnalysisResearchDepth
  quick_model_ref: AnalysisModelReference
  deep_model_ref: AnalysisModelReference
  risk_preference: AnalysisRiskPreference
  investment_horizon: AnalysisInvestmentHorizon
  enabled_skill_versions: string[]
  factor_context: AnalysisFactorContext
  strategy_context: string | null
  debate_rounds: number
  risk_debate_rounds: number
  output_schema_version: string
  disclaimer_profile: string
  change_summary: string
}

export type AnalysisProfileChanges = Omit<AnalysisProfileForm, 'name' | 'change_summary'>
