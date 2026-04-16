
import { db } from '@/lib/prisma';
import { getProxyConfig } from '@/lib/proxy-config';
import { getActiveConfig } from '@/lib/server-config';
import { generateAnswerExtractionPrompt, generateConfigExtractionPrompt } from '@/prompts/config-extraction-prompt';
import { extractKeyActionsFromFlow, mergeKeyActionsFromMultipleSkills, type ExtractedKeyAction, type ParsedFlowResult } from '@/lib/flow-parser';
import { NextResponse } from 'next/server';
import { OpenAI } from "openai";
const pdfParse = require('pdf-parse/lib/pdf-parse.js');

export const dynamic = 'force-dynamic';

async function processConfigAsync(
    configId: string, 
    query: string, 
    standardAnswer: string, 
    documentContent: string | null,
    expectedSkills: { skill: string; version: number | null }[] | null,
    user?: string | null
) {
    try {
        const settings = await getActiveConfig(user);
        if (!settings) {
            console.error(`[ConfigCreate] No model configuration for user: ${user}`);
            await db.updateConfig(configId, { parseStatus: 'failed' });
            return;
        }

        const { customFetch } = getProxyConfig();
        const openaiClient = new OpenAI({
            apiKey: settings.apiKey || 'no-api-key-required',
            baseURL: settings.baseUrl || 'https://api.deepseek.com',
            fetch: customFetch,
        });
        const modelName = settings.model || 'deepseek-chat';

        if (documentContent && !standardAnswer) {
            try {
                const prompt = generateAnswerExtractionPrompt(query, documentContent);
                const response = await openaiClient.chat.completions.create({
                    messages: [{ role: "user", content: prompt }],
                    model: modelName,
                });

                const content = response.choices[0].message.content;
                if (!content) {
                    throw new Error('No content returned from LLM for document extraction');
                }

                let jsonStr = content.trim();
                const matchParse = jsonStr.match(/```(?:json)?\\s*([\\s\\S]*?)\\s*```/i);
                if (matchParse) {
                    jsonStr = matchParse[1];
                } else {
                    const first = jsonStr.indexOf('{');
                    const last = jsonStr.lastIndexOf('}');
                    if (first !== -1 && last !== -1 && last >= first) {
                        jsonStr = jsonStr.substring(first, last + 1);
                    }
                }
                const parsed = JSON.parse(jsonStr);
                standardAnswer = parsed.standard_answer || '';

                if (!standardAnswer) {
                    throw new Error('Extracted standard answer is empty');
                }

                await db.updateConfig(configId, { standardAnswer });

                console.log(`[ConfigCreate] Successfully extracted standard answer for config ${configId}`);
            } catch (e: any) {
                console.error(`[ConfigCreate] Failed to extract standard answer for config ${configId}:`, e.message);
                await db.updateConfig(configId, { parseStatus: 'failed' }).catch(() => {});
                return;
            }
        }

        const prompt = generateConfigExtractionPrompt(query, standardAnswer);

        const response = await openaiClient.chat.completions.create({
            messages: [{ role: "user", content: prompt }],
            model: modelName,
        });

        const content = response.choices[0].message.content;
        if (!content) {
            throw new Error('No content returned from LLM');
        }

        let jsonStr = content.trim();
        const matchParse = jsonStr.match(/```(?:json)?\\s*([\\s\\S]*?)\\s*```/i);
        if (matchParse) {
            jsonStr = matchParse[1];
        } else {
            const first = jsonStr.indexOf('{');
            const last = jsonStr.lastIndexOf('}');
            if (first !== -1 && last !== -1 && last >= first) {
                jsonStr = jsonStr.substring(first, last + 1);
            }
        }
        const extractedData = JSON.parse(jsonStr);
        const rootCauses = extractedData.root_causes || [];
        const keyActionsFromAnswer = extractedData.key_actions || [];

        let finalKeyActions = keyActionsFromAnswer;
        let extractedKeyActionsData: ExtractedKeyAction[] | null = null;

        const skillNamesToExtract = expectedSkills && expectedSkills.length > 0
            ? expectedSkills.map(e => e.skill.trim()).filter(Boolean)
            : [];

        if (skillNamesToExtract.length > 0) {
            try {
                const allActions: { name: string; actions: ExtractedKeyAction[] }[] = [];

                for (const skillName of skillNamesToExtract) {
                    const skill = await db.findSkill(skillName, user || null);
                    if (!skill) {
                        console.warn(`[ConfigCreate] Skill "${skillName}" not found, skipping extraction`);
                        continue;
                    }

                    const targetVersion = skill.activeVersion || 0;
                    const sv = skill.versions?.find((v: any) => v.version === targetVersion) || skill.versions?.[0];
                    if (!sv?.content) continue;

                    const parsedFlow = await db.findParsedFlow(skill.id, sv.version, user || null);
                    if (parsedFlow) {
                        const flow: ParsedFlowResult = JSON.parse(parsedFlow.flowJson);
                        const actions = extractKeyActionsFromFlow(flow);
                        allActions.push({ name: skillName, actions });
                    } else {
                        console.warn(`[ConfigCreate] No parsed flow for skill "${skillName}" v${sv.version}, skipping`);
                    }
                }

                if (allActions.length > 0) {
                    let extractedActions: ExtractedKeyAction[];
                    if (allActions.length === 1) {
                        extractedActions = allActions[0].actions;
                    } else {
                        extractedActions = mergeKeyActionsFromMultipleSkills(allActions);
                    }

                    finalKeyActions = extractedActions.map(a => ({
                        content: a.content,
                        weight: a.weight,
                        ...(a.controlFlowType !== 'required' ? { controlFlowType: a.controlFlowType } : {}),
                        ...(a.condition ? { condition: a.condition } : {}),
                        ...(a.branchLabel ? { branchLabel: a.branchLabel } : {}),
                        ...(a.loopCondition ? { loopCondition: a.loopCondition } : {}),
                        ...(a.expectedMinCount !== undefined ? { expectedMinCount: a.expectedMinCount } : {}),
                        ...(a.expectedMaxCount !== undefined ? { expectedMaxCount: a.expectedMaxCount } : {}),
                        ...(a.groupId ? { groupId: a.groupId } : {}),
                    }));
                    extractedKeyActionsData = extractedActions;

                    console.log(`[ConfigCreate] Extracted ${extractedActions.length} key actions from Skill(s): ${skillNamesToExtract.join(', ')}`);
                }
            } catch (err) {
                console.error('[ConfigCreate] Error extracting key actions from Skill:', err);
            }
        }

        const updateData: any = {
            rootCauses: JSON.stringify(rootCauses),
            keyActions: JSON.stringify(finalKeyActions),
            parseStatus: 'completed'
        };

        if (extractedKeyActionsData) {
            updateData.extractedKeyActions = JSON.stringify(extractedKeyActionsData);
        }

        await db.updateConfig(configId, updateData);

        console.log(`[ConfigCreate] Successfully extracted key points for config ${configId}`);
    } catch (error: any) {
        console.error(`[ConfigCreate] Failed to process config ${configId}:`, error.message);
        await db.updateConfig(configId, { parseStatus: 'failed' }).catch(() => {});
    }
}

export async function POST(request: Request) {
    try {
        const contentType = request.headers.get('content-type') || '';
        
        let query = '';
        let standardAnswer = '';
        let user: string | null = null;
        let documentContent: string | null = null;

        let skill: string | null = null;
        let skillVersion: number | null = null;
        let expectedSkills: { skill: string; version: number | null }[] | null = null;

        if (contentType.includes('multipart/form-data')) {
            const formData = await request.formData();
            query = formData.get('query') as string || '';
            standardAnswer = formData.get('standardAnswer') as string || '';
            user = formData.get('user') as string || null;
            skill = formData.get('skill') as string || null;
            const skillVersionStr = formData.get('skillVersion') as string || null;
            if (skillVersionStr) {
                const parsed = parseInt(skillVersionStr, 10);
                if (!isNaN(parsed) && parsed >= 1) {
                    skillVersion = parsed;
                }
            }
            
            // Parse expectedSkills from JSON string
            const expectedSkillsStr = formData.get('expectedSkills') as string || null;
            if (expectedSkillsStr) {
                try {
                    expectedSkills = JSON.parse(expectedSkillsStr);
                    // Validate expectedSkills structure
                    if (expectedSkills && Array.isArray(expectedSkills)) {
                        // Validate each item has required fields
                        for (const item of expectedSkills) {
                            if (!item || typeof item !== 'object') {
                                return NextResponse.json({ error: 'expectedSkills 数组中的每个元素必须是对象' }, { status: 400 });
                            }
                            if (!item.skill || typeof item.skill !== 'string' || !item.skill.trim()) {
                                return NextResponse.json({ error: 'expectedSkills 中的每个技能必须包含 skill 名称' }, { status: 400 });
                            }
                        }
                        
                        // Normalize versions
                        expectedSkills = expectedSkills.map((item: any) => ({
                            ...item,
                            version: item.version && item.version >= 1 ? item.version : null
                        }));
                    } else if (expectedSkills !== null) {
                        // If expectedSkills is not null but also not an array, it's invalid
                        return NextResponse.json({ error: 'expectedSkills 必须是 JSON 数组' }, { status: 400 });
                    }
                } catch (e) {
                    console.error('Failed to parse expectedSkills:', e);
                    return NextResponse.json({ error: 'expectedSkills JSON 格式无效' }, { status: 400 });
                }
            }

            const file = formData.get('document') as File | null;
            if (file) {
                const fileName = file.name.toLowerCase();
                if (fileName.endsWith('.pdf')) {
                    const arrayBuffer = await file.arrayBuffer();
                    const buffer = Buffer.from(arrayBuffer);
                    const pdfData = await pdfParse(buffer);
                    documentContent = pdfData.text;
                } else {
                    documentContent = await file.text();
                }
            }
        } else {
            const body = await request.json();
            query = body.query || '';
            standardAnswer = body.standardAnswer || '';
            user = body.user || null;
            documentContent = body.documentContent || null;
            skill = body.skill || null;
            skillVersion = body.skillVersion && body.skillVersion >= 1 ? body.skillVersion : null;
            expectedSkills = body.expectedSkills || null;
            // Validate expectedSkills versions
            if (expectedSkills && Array.isArray(expectedSkills)) {
                expectedSkills = expectedSkills.map((item: any) => ({
                    ...item,
                    version: item.version && item.version >= 1 ? item.version : null
                }));
            }
        }

        if (!query) {
            return NextResponse.json({ error: '问题 (Query) 不能为空' }, { status: 400 });
        }

        if (!standardAnswer && !documentContent) {
            return NextResponse.json({ error: '请提供标准答案或上传案例文档' }, { status: 400 });
        }

        const existingConfigs = await db.findConfigs({
            OR: [
                { user: user || null }
            ]
        });
        const existing = existingConfigs.find((c: any) => c.query === query);
        if (existing) {
            return NextResponse.json({ error: '该问题已存在于数据集中' }, { status: 409 });
        }

        const newConfig = await db.createConfig({
            query,
            skill: skill || '',
            skillVersion: skillVersion || null,
            expectedSkills: expectedSkills ? JSON.stringify(expectedSkills) : null,
            standardAnswer: standardAnswer || '',
            rootCauses: null,
            keyActions: null,
            user: user || null,
            parseStatus: 'parsing'
        });

        const formattedConfig = {
            id: newConfig.id,
            query: newConfig.query,
            skill: newConfig.skill,
            skillVersion: newConfig.skillVersion,
            expectedSkills: expectedSkills,
            standard_answer: standardAnswer || (documentContent ? '正在从文档中提取...' : ''),
            root_causes: [],
            key_actions: [],
            parse_status: 'parsing'
        };

        processConfigAsync(newConfig.id, query, standardAnswer, documentContent, expectedSkills, user);

        return NextResponse.json(formattedConfig);

    } catch (error: any) {
        console.error('Config Create Error:', error);
        return NextResponse.json({ error: error.message || 'Internal Server Error' }, { status: 500 });
    }
}
