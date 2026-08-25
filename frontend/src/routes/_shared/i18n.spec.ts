import { describe, expect, it } from 'vitest';
import { translateKey } from './i18n';

describe('research process terminology', () => {
	it('describes collection preparation in researcher-facing Chinese', () => {
		expect(translateKey('zh', 'researchAgent.capability.researchProcessStatus')).toBe(
			'文献分析进度'
		);
		expect(translateKey('zh', 'researchAgent.capability.startResearchProcess')).toBe(
			'开始文献分析'
		);
		expect(translateKey('zh', 'researchAgent.researchProcess.sourceUnderstanding')).toBe(
			'整理论文内容'
		);
		expect(translateKey('zh', 'researchAgent.researchProcess.paperClassification')).toBe(
			'判断论文类型与研究用途'
		);
		expect(translateKey('zh', 'researchAgent.researchProcess.scopeScreening')).toBe(
			'识别材料、变量与结果'
		);
		expect(translateKey('zh', 'researchAgent.researchProcess.objectiveFormation')).toBe(
			'归纳候选研究问题'
		);
	});
});
