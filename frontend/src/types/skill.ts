export interface SkillIOContract {
  input_schema: Record<string, any>;
  output_schema: Record<string, any>;
}

export interface SkillVersion {
  version_id: string;
  skill_id: string;
  version_num: number;
  code: string;
  contract: SkillIOContract;
  checksum: string;
  is_published: boolean;
  commit_message?: string;
  created_at: string;
}

export interface Skill {
  skill_id: string;
  user_id: string;
  name: string;
  description: string;
  skill_type: string;
  is_system_skill: boolean;
  status: string;
  latest_version_num: number;
  published_version_num?: number;
  created_at: string;
  updated_at: string;
}

export interface SkillExecutionResult {
  execution_id: string;
  skill_id: string;
  version_num: number;
  success: boolean;
  result?: Record<string, any>;
  error_message?: string;
  execution_time_ms: number;
  executed_at: string;
}
