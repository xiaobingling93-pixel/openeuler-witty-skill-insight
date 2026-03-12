export function generateFlowParsePrompt(skillContent: string): string {
  return `
你是一个专家，擅长分析 Skill 定义并提取执行流程模式。

给定一个 Skill 定义文档（SKILL.md），你的任务是：
1. 提取预期的执行流程/步骤序列
2. 识别每个步骤应该完成什么（不一定是具体工具）
3. 注意任何条件分支或可选步骤

Skill 定义：
---
${skillContent}
---

请分析 skill 并提取结构化的执行流程。关注：
- 应该执行哪些步骤（按顺序）
- 每个步骤完成什么（目的/目标，不是具体工具名称）
- 步骤是必需的还是可选的
- 任何决策点或分支

请只用 JSON 对象回复，格式如下：
{
  "steps": [
    {
      "id": "step-1",
      "name": "简短的步骤名称（用中文）",
      "description": "这个步骤完成什么",
      "type": "action",
      "isOptional": false
    }
  ],
  "branches": [
    {
      "condition": "条件的描述",
      "trueStepId": "step-x",
      "falseStepId": "step-y"
    }
  ],
  "summary": "整体流程的简要总结"
}

指南：
- "type" 可以是: "action"（做某事）, "decision"（做出选择）, "output"（产生结果）
- 步骤名称要简洁（2-5个字），必须用中文
- 描述应该解释目的，而不是实现方式
- 如果 skill 没有清晰的顺序流程，提取逻辑阶段/阶段
- 如果有工具推荐，在描述中提及但不要作为步骤名称
- 最多10个步骤（如果需要可以合并相关操作）
`;
}

interface FlowStep {
  id: string;
  name: string;
  description: string;
  type: 'action' | 'decision' | 'output';
  isOptional?: boolean;
}

interface FlowBranch {
  condition: string;
  trueStepId: string;
  falseStepId: string;
}

interface ParsedFlow {
  steps: FlowStep[];
  branches?: FlowBranch[];
  summary?: string;
}

export function generateStepExtractPrompt(
  interactions: string,
  batchIndex: number,
  startIndex: number
): string {
  return `
你是一个专家，擅长分析 Agent 执行轨迹并提取执行步骤。

这是第 ${batchIndex + 1} 批对话数据（对话序号从 ${startIndex} 开始）：
---
${interactions}
---

你的任务是：
1. 分析这批对话，提取实际执行的步骤
2. 为每个步骤命名（简洁的中文描述）
3. 记录每个步骤对应的对话序号范围

请只用 JSON 对象回复，格式如下：
{
  "steps": [
    {
      "name": "简短的步骤名称（2-6个中文字）",
      "description": "这个步骤做了什么",
      "dialogStartIndex": 0,
      "dialogEndIndex": 2,
      "type": "action"
    }
  ]
}

指南：
- "name" 必须简洁（2-6个中文字），用于在流程图中显示
- "dialogStartIndex" 和 "dialogEndIndex" 是这批对话中的相对序号（从 ${startIndex} 开始）
- "type" 可以是: "action"（做某事）, "decision"（做出选择）, "output"（产生结果）
- 合并相似的连续操作为一个步骤
- 忽略无关的闲聊或重复内容
- 如果这批对话没有有效步骤，返回空数组 {"steps": []}
- 提取所有有效步骤，不要限制数量
`;
}

export function generateExecutionMatchPrompt(
  expectedFlow: ParsedFlow,
  actualSteps: string,
  skillName: string
): string {
  return `
你是一个专家，擅长分析 Agent 执行轨迹并将其与预期工作流程进行比较。

Skill "${skillName}" 的预期流程：
---
${JSON.stringify(expectedFlow, null, 2)}
---

实际执行步骤：
---
${actualSteps}
---

你的任务是：
1. 为每个实际执行步骤生成一条匹配记录（放在 matches 数组）
2. 将实际步骤与预期流程匹配，或标记为意外步骤
3. 找出所有未被实际执行匹配的预期步骤（放在 skippedExpectedSteps 数组）
4. 为有问题的步骤提供详细分析

请只用 JSON 对象回复，格式如下：
{
  "matches": [
    {
      "expectedStepId": "step-1",
      "expectedStepName": "预期流程中的步骤名称",
      "actualStepIndex": 0,
      "actualAction": "简洁的操作描述（2-6个中文字，用于图表显示）",
      "matchStatus": "matched",
      "matchReason": "简要解释"
    }
  ],
  "skippedExpectedSteps": [
    {
      "expectedStepId": "step-3",
      "expectedStepName": "被跳过的预期步骤名称"
    }
  ],
  "summary": {
    "totalSteps": 5,
    "matchedSteps": 3,
    "partialSteps": 0,
    "unexpectedSteps": 1,
    "skippedSteps": 1,
    "orderViolations": 0,
    "overallScore": 0.75
  },
  "problemSteps": [
    {
      "stepIndex": 2,
      "stepName": "步骤名称",
      "status": "unexpected",
      "problem": "问题描述",
      "suggestion": "改进建议"
    }
  ]
}

匹配状态值（只用于 matches 数组）：
- "matched": 步骤与预期流程匹配良好（符合预期）
- "partial": 步骤部分匹配，意图正确但执行方式有问题（部分偏离）
- "unexpected": 步骤完全不在预期流程中（非预期调用）

重要规则：
1. matches 数组：必须包含每个实际执行步骤的记录，不能遗漏任何实际步骤
2. matches 数组中的 matchStatus 只能是 "matched"、"partial" 或 "unexpected"，不能是 "skipped"
3. skippedExpectedSteps 数组：包含所有未被实际执行匹配的预期步骤（即被跳过的预期步骤）
4. actualAction 必须简洁（20个中文字以内），用于在流程图中显示
5. problemSteps 只包含有问题的步骤（status 为 partial 或 unexpected 的步骤）

评分指南：
- matched: 贡献 1.0 分
- partial: 贡献 0.5 分  
- unexpected: 贡献 -0.2 分（惩罚）
- skipped: 贡献 0 分
- orderViolations: 每个 -0.1 分惩罚
`;
}
