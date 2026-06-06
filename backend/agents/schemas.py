from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal, Any, Union

# --- Analyzer Models ---
class CompetitorValue(BaseModel):
    value: str = Field(description="concise extracted fact or short synthesized answer")
    status: Literal["accepted", "degraded"]
    source_url: Optional[str] = None
    evidence_refs: List[str]
    degraded_reason: Optional[str] = None

class ComparisonRow(BaseModel):
    key: str
    dimension_id: str
    dimension: str
    values: Dict[str, CompetitorValue]

class LegacyComparison(BaseModel):
    competitor: str
    summary: str = Field(description="evidence-backed competitive position")
    status: Literal["accepted", "degraded"]
    evidence_refs: List[str]

class SwotItem(BaseModel):
    text: str = Field(description="competitor-specific insight or market/risk insight")
    evidence_refs: List[str]

class SwotAnalysis(BaseModel):
    strengths: List[SwotItem]
    weaknesses: List[SwotItem]
    opportunities: List[SwotItem]
    threats: List[SwotItem]
    so_strategies: List[SwotItem] = []
    wo_strategies: List[SwotItem] = []
    st_strategies: List[SwotItem] = []
    wt_strategies: List[SwotItem] = []
    competitor: str = ""

class Finding(BaseModel):
    title: str
    detail: str = Field(description="analysis")
    evidence_refs: List[str]

class Recommendation(BaseModel):
    text: str = Field(description="actionable recommendation")
    evidence_refs: List[str]

class Report(BaseModel):
    summary: str = Field(description="deep comparative executive summary")
    findings: List[Finding]
    recommendations: List[Recommendation]
    source_appendix: List[Any] = []

class SchemaDimension(BaseModel):
    id: str
    name: str
    group: str

class AnalysisResult(BaseModel):
    discovered_competitors: List[str]
    schema_dimensions: List[SchemaDimension]
    comparison_rows: List[ComparisonRow]
    comparison: List[LegacyComparison]
    swot: SwotAnalysis
    report: Report
    evidence_refs: List[str]

# --- Critic Models ---
class CriticFeedback(BaseModel):
    level: str = Field(default="L2")
    target_type: str = Field(default="analysis_result")
    target_id: str = Field(default="analysis")
    module_id: str = Field(default="analysis")
    severity: Literal["warning", "error"]
    code: str = Field(description="short_code")
    message: str = Field(description="specific issue")
    suggested_action: Literal["retry_collection", "retry_analysis", "extend_schema", "human_review", "review", "manual_review"]
    retry_count: int = Field(default=0)

class SchemaExtension(BaseModel):
    dimension_group: str = Field(description="Feature Tree, Extended Attributes, etc.")
    new_field: str = Field(description="e.g. Open source license support")
    confidence: float
    evidence: List[str] = Field(description="brief evidence from supplied materials")
    affected_competitors: List[str]

class CriticResult(BaseModel):
    feedback: List[CriticFeedback]
    suggested_schema_extensions: List[SchemaExtension]

# --- Orchestrator Models ---

CollectorSkillType = Literal["product", "business", "technical", "company"]

class SchemaFieldInfo(BaseModel):
    name: str
    type: str = "text"
    required: bool = True
    reason: Optional[str] = Field(None, description="why useful")
    skill_category: CollectorSkillType = Field(
        default="company",
        description="Choose the most appropriate extraction skill for this field."
    )

class PlanCompletionResult(BaseModel):
    competitors: List[str]
    schema_def: Dict[str, List[SchemaFieldInfo]]

class CompetitorCandidateModel(BaseModel):
    name: str = Field(description="short product or company name")
    reason: str = Field(description="one concise reason why it is a competitor")
    source_urls: List[str] = Field(default_factory=list, description="add URL from search results if applicable")
    confidence: float = Field(description="number from 0 to 1")

class CompetitorRecommendationResult(BaseModel):
    candidates: List[CompetitorCandidateModel]
