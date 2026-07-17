import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({
	requestJson
}));

const {
	createResearchUnderstandingCuration,
	createResearchUnderstandingFeedback,
	exportResearchUnderstandingGoldDraft,
	fetchResearchUnderstandingFeedback,
	fetchResearchUnderstandingCurations,
	importResearchUnderstandingReviewDecisions,
	fetchResearchUnderstandingDataset,
	fetchCollectionObjectives,
	fetchCollectionMaterials,
	fetchCollectionResearchView,
	fetchConfirmedGoals,
	fetchDocumentResearchView,
	fetchGoalAnalysis,
	fetchObjectiveResearchView,
	fetchMaterialResearchView,
	formatShortIdentifier,
	formatEvidenceBackedValue,
	getResearchViewStateTone,
	hasObservedValue,
	normalizeCollectionAggregation,
	normalizeEvidenceBackedValue,
	normalizeObjectiveResearchView,
	normalizePaperAggregation,
	researchUnderstandingCollectionDatasetUrl,
	researchUnderstandingDatasetUrl
} = await import('./researchView');

describe('research view shared helpers', () => {
	beforeEach(() => {
		requestJson.mockReset();
	});

	it('builds traceable training dataset export urls', () => {
		expect(
			researchUnderstandingDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					scope_id: 'goal 1',
					dataset_use_status: 'training_ready'
				},
				'training_jsonl'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset?scope_type=goal&scope_id=goal+1&dataset_use_status=training_ready&format=training_jsonl'
		);
		expect(
			researchUnderstandingCollectionDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					dataset_use_status: 'training_ready'
				},
				'training_jsonl'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset/collection?scope_type=goal&dataset_use_status=training_ready&format=training_jsonl'
		);
	});

	it('builds review packet dataset export urls', () => {
		expect(
			researchUnderstandingDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					scope_id: 'goal 1',
					dataset_use_status: 'review_candidate'
				},
				'review_packet'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset?scope_type=goal&scope_id=goal+1&dataset_use_status=review_candidate&format=review_packet'
		);
		expect(
			researchUnderstandingCollectionDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					dataset_use_status: 'review_candidate'
				},
				'review_packet'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset/collection?scope_type=goal&dataset_use_status=review_candidate&format=review_packet'
		);
	});

	it('builds review decision template dataset export urls', () => {
		expect(
			researchUnderstandingDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					scope_id: 'goal 1',
					dataset_use_status: 'review_candidate'
				},
				'decision_template'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset?scope_type=goal&scope_id=goal+1&dataset_use_status=review_candidate&format=decision_template'
		);
		expect(
			researchUnderstandingCollectionDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					dataset_use_status: 'review_candidate'
				},
				'decision_template'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset/collection?scope_type=goal&dataset_use_status=review_candidate&format=decision_template'
		);
	});

	it('builds review decision board TSV export urls', () => {
		expect(
			researchUnderstandingDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					scope_id: 'goal 1',
					dataset_use_status: 'review_candidate'
				},
				'decision_board_tsv'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset?scope_type=goal&scope_id=goal+1&dataset_use_status=review_candidate&format=decision_board_tsv'
		);
		expect(
			researchUnderstandingCollectionDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					dataset_use_status: 'review_candidate'
				},
				'decision_board_tsv'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset/collection?scope_type=goal&dataset_use_status=review_candidate&format=decision_board_tsv'
		);
	});

	it('builds agent review prompt dataset export urls', () => {
		expect(
			researchUnderstandingDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					scope_id: 'goal 1',
					dataset_use_status: 'review_candidate'
				},
				'agent_review_prompt_jsonl'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset?scope_type=goal&scope_id=goal+1&dataset_use_status=review_candidate&format=agent_review_prompt_jsonl'
		);
		expect(
			researchUnderstandingCollectionDatasetUrl(
				'col 1',
				{
					scope_type: 'goal',
					dataset_use_status: 'review_candidate'
				},
				'agent_review_prompt_jsonl'
			)
		).toBe(
			'/api/v1/collections/col%201/research-understanding/dataset/collection?scope_type=goal&dataset_use_status=review_candidate&format=agent_review_prompt_jsonl'
		);
	});

	it('fetches collection and document research views through same-origin api paths', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			state: 'ready',
			overview: {
				material_systems: ['316L stainless steel']
			}
		});

		const collection = await fetchCollectionResearchView('col_123');

		expect(requestJson).toHaveBeenCalledWith('/collections/col_123/research-view');
		expect(collection.state).toBe('ready');
		expect(collection.overview.material_systems).toEqual(['316L stainless steel']);

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			document_id: 'doc_1',
			state: 'partial',
			paper_title: 'SLM 316L'
		});

		const paper = await fetchDocumentResearchView('col_123', 'doc_1');

		expect(requestJson).toHaveBeenLastCalledWith(
			'/collections/col_123/documents/doc_1/research-view'
		);
		expect(paper.paper_title).toBe('SLM 316L');

		requestJson.mockResolvedValueOnce({
			items: [
				{
					material_id: 'mat_316l',
					canonical_name: '316L stainless steel',
					aliases: ['316L'],
					paper_count: 2,
					sample_count: 6,
					evidence_coverage: 0.8,
					state: 'ready'
				}
			]
		});

		const materials = await fetchCollectionMaterials('col_123');

		expect(requestJson).toHaveBeenLastCalledWith('/collections/col_123/materials');
		expect(materials[0]).toMatchObject({
			material_id: 'mat_316l',
			canonical_name: '316L stainless steel',
			sample_count: 6
		});

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			material_id: 'mat_316l',
			canonical_name: '316L stainless steel',
			state: 'ready',
			papers: [{ document_id: 'doc_1', source_filename: 'paper-a.pdf', state: 'ready' }],
			sample_matrix: {
				rows: [{ row_id: 'row_1', sample_id: 'S1', sample_label: 'S1', material: '316L' }]
			},
			understanding: {
				schema_version: 'research_understanding.v1',
				state: 'ready',
				scope: {
					scope_type: 'material',
					collection_id: 'col_123',
					material_id: 'mat_316l',
					title: '316L stainless steel'
				},
				claims: [
					{
						claim_id: 'claim_1',
						claim_type: 'finding',
						statement: '316L has traceable density evidence.',
						status: 'supported',
						evidence_ref_ids: ['E001']
					}
				],
				relations: [],
				evidence_refs: [
					{
						evidence_ref_id: 'E001',
						source_kind: 'table',
						document_id: 'doc_1',
						label: 'P001 Table 1',
						traceability_status: 'resolved'
					}
				],
				contexts: [],
				warnings: [],
				summary: { claim_count: 1, relation_count: 0, evidence_ref_count: 1, context_count: 0 }
			}
		});

		const materialProfile = await fetchMaterialResearchView('col_123', 'mat_316l');

		expect(requestJson).toHaveBeenLastCalledWith(
			'/collections/col_123/materials/mat_316l/research-view'
		);
		expect(materialProfile.papers[0].document_id).toBe('doc_1');
		expect(materialProfile.papers[0].title).toBe('paper-a.pdf');
		expect(materialProfile.papers[0].source_filename).toBe('paper-a.pdf');
		expect(materialProfile.sample_matrix.rows[0].sample_id).toBe('S1');
		expect(materialProfile.understanding?.claims[0].statement).toBe(
			'316L has traceable density evidence.'
		);
		expect(materialProfile.understanding?.evidence_refs[0].label).toBe('P001 Table 1');

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			state: 'partial',
			readiness: {
				objectives_ready: true,
				frames_ready: true,
				routes_ready: false,
				evidence_units_ready: false,
				logic_chain_ready: false
			},
			objectives: [
				{
					objective_id: 'obj_1',
					question: 'How does heat treatment affect corrosion resistance?',
					material_scope: ['316L stainless steel'],
					process_axes: ['heat treatment'],
					property_axes: ['corrosion resistance'],
					state: 'partial',
					paper_frame_count: 2
				}
			]
		});

		const objectives = await fetchCollectionObjectives('col_123');

		expect(requestJson).toHaveBeenLastCalledWith('/collections/col_123/objectives');
		expect(objectives.objectives[0].objective_id).toBe('obj_1');
		expect(objectives.objectives[0].paper_frame_count).toBe(2);

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			goals: [
				{
					goal_id: 'goal_1',
					collection_id: 'col_123',
					question: 'How does heat treatment affect corrosion resistance?',
					source_type: 'objective_candidate',
					status: 'ready',
					source_objective_id: 'obj_1'
				}
			]
		});

		const goals = await fetchConfirmedGoals('col_123');

		expect(requestJson).toHaveBeenLastCalledWith('/collections/col_123/goals');
		expect(goals.goals[0].goal_id).toBe('goal_1');
		expect(goals.goals[0].status).toBe('ready');

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			state: 'partial',
			objective: {
				objective_id: 'obj_1',
				question: 'How does heat treatment affect corrosion resistance?'
			},
			readiness: {
				objectives_ready: true,
				frames_ready: true,
				routes_ready: false,
				evidence_units_ready: false,
				logic_chain_ready: false
			},
			paper_frames: [{ frame_id: 'opf_1', document_id: 'doc_1', relevance: 'high' }],
			evidence_routes: [],
			evidence_units: [],
			logic_chain: null,
			understanding: {
				schema_version: 'research_understanding.v1',
				state: 'limited',
				scope: {
					scope_type: 'objective',
					collection_id: 'col_123',
					objective_id: 'obj_1',
					title: 'How does heat treatment affect corrosion resistance?'
				},
				claims: [
					{
						claim_id: 'claim_obj_1',
						claim_type: 'finding',
						statement: 'Current evidence is limited.',
						status: 'limited'
					}
				],
				relations: [],
				evidence_refs: [],
				contexts: [],
				warnings: ['claims_without_evidence_refs'],
				summary: { claim_count: 1, relation_count: 0, evidence_ref_count: 0, context_count: 0 }
			}
		});

		const objectiveView = await fetchObjectiveResearchView('col_123', 'obj_1');

		expect(requestJson).toHaveBeenLastCalledWith(
			'/collections/col_123/objectives/obj_1/research-view'
		);
		expect(objectiveView.objective.objective_id).toBe('obj_1');
		expect(objectiveView.paper_frames[0].frame_id).toBe('opf_1');
		expect(objectiveView.understanding?.state).toBe('limited');
		expect(objectiveView.understanding?.claims[0].statement).toBe('Current evidence is limited.');
	});

	it('normalizes confirmed goal analysis progress', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			goal: {
				goal_id: 'goal_1',
				collection_id: 'col_123',
				question: 'How does heat treatment affect strength?',
				source_type: 'objective_candidate',
				material_hints: ['316L stainless steel'],
				process_hints: ['heat treatment'],
				property_hints: ['yield strength'],
				source_objective_id: 'obj_1',
				status: 'running',
				analysis_error: null,
				analysis_progress: {
					phase: 'objective_evidence_routing_started',
					current: '3',
					total: 6,
					unit: 'frames',
					message: 'Routing source blocks and tables.',
					active_document_id: 'doc_1',
					active_document_title: 'Heat treatment study',
					active_source_filename: 'heat-treatment.pdf',
					active_objective_id: 'obj_1'
				}
			},
			understanding: null,
			pipeline_nodes: {},
			errors: [],
			warnings: []
		});

		const analysis = await fetchGoalAnalysis('col_123', 'goal_1');

		expect(requestJson).toHaveBeenCalledWith('/collections/col_123/goals/goal_1/analysis');
		expect(analysis.goal.status).toBe('running');
		expect(analysis.goal.analysis_progress).toMatchObject({
			phase: 'objective_evidence_routing_started',
			current: 3,
			total: 6,
			unit: 'frames',
			active_document_title: 'Heat treatment study'
		});
	});

	it('normalizes research understanding findings on confirmed goal analysis', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			goal: {
				goal_id: 'goal_1',
				collection_id: 'col_123',
				question: 'How does heat treatment affect strength?',
				source_type: 'objective_candidate',
				status: 'ready'
			},
			understanding: {
				schema_version: 'research_understanding.v1',
				state: 'ready',
				scope: {
					scope_type: 'goal',
					collection_id: 'col_123',
					goal_id: 'goal_1',
					title: 'How does heat treatment affect strength?'
				},
				claims: [
					{
						claim_id: 'claim_1',
						claim_type: 'finding',
						statement: 'Heat treatment changes tensile strength.',
						status: 'supported'
					}
				],
				relations: [],
				evidence_refs: [
					{
						evidence_ref_id: 'ev_1',
						source_kind: 'table',
						document_id: 'doc_1',
						label: 'P001 Table 2',
						traceability_status: 'traceable',
						evidence_role: 'direct_support'
					}
				],
				contexts: [],
				summary: {
					claim_count: 1,
					relation_count: 0,
					evidence_ref_count: 1,
					context_count: 0
				},
				presentation: {
					summary: {
						primary_finding_count: 1,
						review_queue_finding_count: 1
					},
					findings: [
						{
							finding_id: 'finding_claim_1',
							claim_id: 'claim_1',
							title: 'heat treatment -> tensile strength',
							statement: 'Heat treatment changes tensile strength.',
							variables: ['heat treatment'],
							outcomes: ['tensile strength'],
							support_grade: 'partial',
							review_status: 'pending_review',
							synthesis_status: 'condition_dependent',
							common_conditions: ['LPBF 316L'],
							incomparable_conditions: ['different tensile temperatures'],
							paper_contributions: [
								{
									document_id: 'doc_1',
									title: 'Heat treatment study',
									source_filename: 'heat-treatment.pdf',
									role: 'supporting',
									statement: 'The paper reports a condition-specific strength change.',
									evidence_ref_ids: ['ev_1']
								}
							],
							evidence_ref_ids: ['ev_1'],
							relation_chain: [
								{
									relation_id: 'rel_1',
									variable: 'heat treatment',
									mediators: ['recrystallization'],
									outcome: 'tensile strength',
									direction: 'condition-dependent',
									statement: 'The source reports a condition-specific association.'
								}
							],
							evidence_bundle: {
								direct_result: ['ev_1']
							}
						},
						{
							finding_id: 'finding_claim_review',
							claim_id: 'claim_review',
							title: 'background -> tensile strength',
							statement: 'Background-only candidate.',
							variables: ['background'],
							outcomes: ['tensile strength'],
							support_grade: 'insufficient',
							review_status: 'needs_review',
							evidence_ref_ids: [],
							evidence_bundle: {
								background: ['ev_background']
							}
						}
					],
					primary_findings: [
						{
							finding_id: 'finding_claim_1',
							claim_id: 'claim_1',
							title: 'heat treatment -> tensile strength',
							statement: 'Heat treatment changes tensile strength.',
							variables: ['heat treatment'],
							outcomes: ['tensile strength'],
							support_grade: 'partial',
							review_status: 'pending_review',
							evidence_ref_ids: ['ev_1'],
							evidence_bundle: {
								direct_result: ['ev_1']
							}
						}
					],
					review_queue_findings: [
						{
							finding_id: 'finding_claim_review',
							claim_id: 'claim_review',
							title: 'background -> tensile strength',
							statement: 'Background-only candidate.',
							variables: ['background'],
							outcomes: ['tensile strength'],
							support_grade: 'insufficient',
							review_status: 'needs_review',
							evidence_ref_ids: [],
							evidence_bundle: {
								background: ['ev_background']
							}
						}
					],
					evidence_items: [
						{
							evidence_ref_id: 'ev_1',
							document_id: 'doc_1',
							title: 'P001 Table 2 / p. 5',
							source_label: 'P001 Table 2',
							source_kind: 'table',
							table_audit: {
								columns: ['Condition', 'Strength', 'Elongation'],
								relevant_rows: [
									{ row_index: 1, cells: ['As built', '450', '12'] },
									{ row_index: 2, cells: ['Parsed short row', '470'], aligned: false }
								]
							},
							traceability_status: 'traceable',
							evidence_role: 'direct_support'
						}
					]
				}
			},
			pipeline_nodes: {},
			errors: [],
			warnings: []
		});

		const analysis = await fetchGoalAnalysis('col_123', 'goal_1');
		const finding = analysis.understanding?.presentation.findings[0];

		expect(requestJson).toHaveBeenCalledWith('/collections/col_123/goals/goal_1/analysis');
		expect(finding).toMatchObject({
			finding_id: 'finding_claim_1',
			variables: ['heat treatment'],
			outcomes: ['tensile strength'],
			support_grade: 'partial',
			review_status: 'pending_review'
		});
		expect(finding?.evidence_bundle.direct_result).toEqual(['ev_1']);
		expect(finding?.synthesis_status).toBe('condition_dependent');
		expect(finding?.common_conditions).toEqual(['LPBF 316L']);
		expect(finding?.incomparable_conditions).toEqual(['different tensile temperatures']);
		expect(finding?.paper_contributions).toEqual([
			{
				document_id: 'doc_1',
				title: 'Heat treatment study',
				source_filename: 'heat-treatment.pdf',
				role: 'supporting',
				statement: 'The paper reports a condition-specific strength change.',
				evidence_ref_ids: ['ev_1']
			}
		]);
		expect(finding?.relation_chain).toEqual([
			{
				relation_id: 'rel_1',
				variable: 'heat treatment',
				mediators: ['recrystallization'],
				outcome: 'tensile strength',
				direction: 'condition-dependent',
				statement: 'The source reports a condition-specific association.'
			}
		]);
		expect(analysis.understanding?.presentation.summary.primary_finding_count).toBe(1);
		expect(analysis.understanding?.presentation.summary.review_queue_finding_count).toBe(1);
		expect(analysis.understanding?.presentation.primary_findings.map((item) => item.finding_id)).toEqual([
			'finding_claim_1'
		]);
		expect(
			analysis.understanding?.presentation.review_queue_findings.map((item) => item.finding_id)
		).toEqual(['finding_claim_review']);
		expect(analysis.understanding?.evidence_refs[0].evidence_role).toBe('direct_support');
		expect(analysis.understanding?.presentation.evidence_items[0].evidence_role).toBe(
			'direct_support'
		);
		expect(
			analysis.understanding?.presentation.evidence_items[0].table_audit?.relevant_rows
		).toEqual([
			{ row_index: 1, cells: ['As built', '450', '12'], aligned: true },
			{ row_index: 2, cells: ['Parsed short row', '470'], aligned: false }
		]);
	});

	it('posts research understanding feedback through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			feedback_id: 'ruf_1',
			collection_id: 'col_123',
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_1',
			claim_id: 'claim_1',
			review_status: 'incorrect',
			issue_type: 'evidence_not_grounded',
			note: 'The claim cites the wrong table.',
			reviewer: 'materials-expert',
			created_at: '2026-06-18T09:00:00+00:00'
		});

		const feedback = await createResearchUnderstandingFeedback('col_123', {
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_1',
			claim_id: 'claim_1',
			review_status: 'incorrect',
			issue_type: 'evidence_not_grounded',
			note: 'The claim cites the wrong table.',
			reviewer: 'materials-expert'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/feedback',
			{
				method: 'POST',
				body: JSON.stringify({
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_1',
					claim_id: 'claim_1',
					review_status: 'incorrect',
					issue_type: 'evidence_not_grounded',
					note: 'The claim cites the wrong table.',
					reviewer: 'materials-expert'
				})
			}
		);
		expect(feedback.feedback_id).toBe('ruf_1');
	});

	it('posts research understanding review decisions through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			status: 'pass',
			dry_run: true,
			total_rows: 1,
			written_count: 0,
			skipped_count: 0,
			counts: { accept: 1 },
			errors: [],
			warnings: [],
			review_progress: { ready_to_write: true },
			decision_progress_by_goal: [],
			affected_goals: [],
			readiness_summary: {}
		});

		const payload = {
			dry_run: true,
			fail_on_warnings: true,
			rows: [
				{
					goal_id: 'goal_1',
					finding_id: 'finding_1',
					action: 'accept'
				}
			]
		};
		const summary = await importResearchUnderstandingReviewDecisions('col 123', payload);

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col%20123/research-understanding/review-decisions/import',
			{
				method: 'POST',
				body: JSON.stringify(payload)
			}
		);
		expect(summary.review_progress.ready_to_write).toBe(true);
	});

	it('posts decision board TSV review imports through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			status: 'pass',
			dry_run: true,
			total_rows: 1,
			written_count: 0,
			skipped_count: 0,
			counts: { correct: 1 },
			errors: [],
			warnings: [],
			review_progress: { ready_to_write: true },
			decision_progress_by_goal: [],
			affected_goals: [],
			readiness_summary: {}
		});

		const payload = {
			dry_run: true,
			fail_on_warnings: true,
			decision_board_tsv:
				'expert_action\tcollection_id\tgoal_id\tfinding_id\ncorrect\tcol 123\tgoal_1\tfinding_1\n'
		};
		const summary = await importResearchUnderstandingReviewDecisions('col 123', payload);

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col%20123/research-understanding/review-decisions/import',
			{
				method: 'POST',
				body: JSON.stringify(payload)
			}
		);
		expect(summary.counts.correct).toBe(1);
	});

	it('lists research understanding feedback through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			items: [
				{
					feedback_id: 'ruf_1',
					collection_id: 'col_123',
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_1',
					claim_id: 'claim_1',
					review_status: 'incorrect',
					issue_type: 'evidence_not_grounded',
					note: 'The claim cites the wrong table.',
					reviewer: 'materials-expert',
					created_at: '2026-06-18T09:00:00+00:00'
				}
			]
		});

		const feedback = await fetchResearchUnderstandingFeedback('col_123', {
			scope_type: 'objective',
			scope_id: 'obj_1'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/feedback?scope_type=objective&scope_id=obj_1'
		);
		expect(feedback[0].feedback_id).toBe('ruf_1');
		expect(feedback[0].review_status).toBe('incorrect');
	});

	it('posts expert claim curation through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			curation_id: 'ruc_1',
			collection_id: 'col_123',
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_1',
			claim_id: 'claim_1',
			curated_claim_type: 'mechanism',
			curated_status: 'limited',
			curated_statement: 'Nitrogen improves strength with limited mechanism evidence.',
			curated_evidence_ref_ids: ['ev_1'],
			curated_context_ids: ['ctx_1'],
			note: 'Needs microstructure evidence before marking supported.',
			reviewer: 'materials-expert',
			updated_at: '2026-06-18T09:00:00+00:00'
		});

		const curation = await createResearchUnderstandingCuration('col_123', {
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_1',
			claim_id: 'claim_1',
			curated_claim_type: 'mechanism',
			curated_status: 'limited',
			curated_statement: 'Nitrogen improves strength with limited mechanism evidence.',
			curated_evidence_ref_ids: ['ev_1'],
			curated_context_ids: ['ctx_1'],
			note: 'Needs microstructure evidence before marking supported.',
			reviewer: 'materials-expert'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/curations',
			{
				method: 'POST',
				body: JSON.stringify({
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_1',
					claim_id: 'claim_1',
					curated_claim_type: 'mechanism',
					curated_status: 'limited',
					curated_statement: 'Nitrogen improves strength with limited mechanism evidence.',
					curated_evidence_ref_ids: ['ev_1'],
					curated_context_ids: ['ctx_1'],
					note: 'Needs microstructure evidence before marking supported.',
					reviewer: 'materials-expert'
				})
			}
		);
		expect(curation.curation_id).toBe('ruc_1');
	});

	it('lists expert claim curations through the same-origin collection contract', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			items: [
				{
					curation_id: 'ruc_1',
					collection_id: 'col_123',
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_1',
					claim_id: 'claim_1',
					curated_claim_type: 'mechanism',
					curated_status: 'limited',
					curated_statement: 'Nitrogen improves strength with limited mechanism evidence.',
					curated_evidence_ref_ids: ['ev_1'],
					curated_context_ids: ['ctx_1'],
					note: 'Needs microstructure evidence before marking supported.',
					reviewer: 'materials-expert',
					updated_at: '2026-06-18T09:00:00+00:00'
				}
			]
		});

		const curations = await fetchResearchUnderstandingCurations('col_123', {
			scope_type: 'objective',
			scope_id: 'obj_1'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/curations?scope_type=objective&scope_id=obj_1'
		);
		expect(curations[0].curation_id).toBe('ruc_1');
		expect(curations[0].curated_status).toBe('limited');
	});

	it('exports research understanding curation gold drafts through the same-origin contract', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			scope_type: 'objective',
			scope_id: 'obj_1',
			gold_id: 'gold_col_123_objective_obj_1_research_understanding',
			target_layer: 'core',
			metric_profile: 'research_understanding_v1',
			item_count: 1,
			items: [
				{
					gold_item_id: 'gold_finding_1',
					document_id: '',
					family: 'research_understanding_findings',
					item_key: 'objective:obj_1:finding_1',
					payload: { finding_id: 'finding_1', claim_id: 'claim_1', claim_type: 'mechanism' },
					evidence_refs: [{ evidence_ref_id: 'ev_1' }],
					metadata: { curation_id: 'ruc_1' }
				}
			]
		});

		const draft = await exportResearchUnderstandingGoldDraft('col_123', {
			scope_type: 'objective',
			scope_id: 'obj_1'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/gold-draft?scope_type=objective&scope_id=obj_1'
		);
		expect(draft.item_count).toBe(1);
		expect(draft.items[0].family).toBe('research_understanding_findings');
	});

	it('normalizes research understanding dataset review risk summaries', async () => {
		requestJson.mockResolvedValueOnce({
			schema_version: 'research_understanding_dataset.v1',
			dataset_id: 'rud_col_123_goal_goal_1',
			collection_id: 'col_123',
			scope_type: 'goal',
			scope_id: 'goal_1',
			task_type: 'research_understanding_finding',
			metric_profile: 'research_understanding_finding.v1',
			label_status_filter: null,
			dataset_use_status_filter: null,
			item_count: 2,
			label_counts: {
				candidate: 2,
				silver: 0,
				gold: 0,
				rejected: 0
			},
			quality_summary: {
				training_ready_sample_count: 0,
				training_message_sample_count: 0,
				protocol_ready_sample_count: 1,
				review_candidate_sample_count: 2,
				next_review_finding_id: 'finding_1',
				by_dataset_use_status: {
					training_ready: 0,
					review_candidate: 2,
					rejected: 0
				},
				by_presentation_bucket: {
					primary: 1,
					review_queue: 1
				},
				by_error_category: {
					unreviewed: 2
				},
				by_review_reason: {
					single_paper_evidence: 2,
					partial_support: 1
				},
				by_system_warning: {
					table_row_alignment_uncertain: 1
				},
				by_review_candidate_reason: {
					single_paper_evidence: 1
				},
				by_review_candidate_warning: {
					table_row_alignment_uncertain: 1
				},
				optimization_breakdown: {
					by_variable: {
						'scan speed': {
							issue_type: {
								wrong_direction: 1,
								none: 0
							},
							error_category: {
								direction_error: 1
							},
							review_candidate_reason: {
								table_row_needs_expert_review: 1
							},
							system_warning: {
								table_row_alignment_uncertain: 1
							}
						}
					},
					by_evidence_role: {
						table_row: {
							issue_type: {},
							error_category: {},
							review_candidate_reason: {
								table_row_needs_expert_review: 1
							},
							system_warning: {
								table_row_alignment_uncertain: 1
							}
						}
					}
				},
				top_error_categories: [{ name: 'unreviewed', count: 2 }],
				top_issue_types: [{ name: 'unreviewed', count: 2 }],
				top_review_reasons: [
					{ name: 'single_paper_evidence', count: 2 },
					{ name: 'partial_support', count: 1 }
				],
				top_system_warnings: [{ name: 'table_row_alignment_uncertain', count: 1 }],
				top_variable_issue_types: [
					{ name: 'scan speed', metric: 'wrong_direction', count: 1 }
				],
				top_outcome_issue_types: [{ name: 'density', metric: 'wrong_direction', count: 1 }],
				top_direction_issue_types: [
					{ name: 'condition-dependent', metric: 'wrong_direction', count: 1 }
				],
				top_evidence_role_issue_types: [
					{ name: 'table_row', metric: 'wrong_direction', count: 1 }
				],
				top_variable_review_reasons: [
					{ name: 'scan speed', metric: 'table_row_needs_expert_review', count: 1 }
				],
				top_outcome_review_reasons: [
					{ name: 'density', metric: 'table_row_needs_expert_review', count: 1 }
				],
				top_direction_review_reasons: [
					{
						name: 'condition-dependent',
						metric: 'table_row_needs_expert_review',
						count: 1
					}
				],
				top_evidence_role_review_reasons: [
					{ name: 'table_row', metric: 'table_row_needs_expert_review', count: 1 }
				]
			},
			items: [
					{
						sample_id: 'sample_1',
						finding_id: 'finding_1',
						claim_id: 'claim_1',
						label_status: 'silver',
						dataset_use_status: 'review_candidate',
					review_action: {
						code: 'verify_table_rows',
						label: 'verify parsed table rows before accepting or correcting'
					},
					protocol_readiness: {
						status: 'ready_after_review',
						ready_after_review: true,
						missing: ['expert_review_decision'],
						blocking_missing: [],
						checks: {
							expert_review_decision: false,
							statement: true,
							variables: true
						},
						guidance: 'accept or correct before protocol use'
					},
							acceptance_gate: {
								status: 'review_required',
								accept_allowed: true,
							requires_correction: false,
							blocking_missing: [],
							accept_blockers: [
								'verify_table_rows',
								'table_row_alignment_uncertain'
							],
							review_checks: ['Confirm paper-level scope.'],
								recommended_action_code: 'verify_table_rows',
								guidance: 'Accept only after checking source evidence.'
						},
						review_decision_hint: {
							summary: 'Verify parsed table rows before accepting.',
							preferred_next_action: 'verify_then_accept_or_correct',
							allowed_actions: ['accept', 'reject', 'correct', 'skip'],
							blocked_actions: [],
							why_accept_blocked: [],
							required_checks: ['Confirm paper-level scope.'],
							import_note: 'accept imports only after the reviewer changes action from skip'
						},
						metadata: {
							training_message_diagnostic: ['missing_message_pair']
					}
				}
			],
			warnings: []
		});

		const dataset = await fetchResearchUnderstandingDataset('col_123', {
			scope_type: 'goal',
			scope_id: 'goal_1'
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/research-understanding/dataset?scope_type=goal&scope_id=goal_1'
		);
		expect(dataset.quality_summary.by_review_reason).toEqual({
			single_paper_evidence: 2,
			partial_support: 1
		});
		expect(dataset.quality_summary.protocol_ready_sample_count).toBe(1);
		expect(dataset.quality_summary.by_system_warning).toEqual({
			table_row_alignment_uncertain: 1
		});
		expect(dataset.quality_summary.by_review_candidate_reason).toEqual({
			single_paper_evidence: 1
		});
		expect(dataset.quality_summary.by_review_candidate_warning).toEqual({
			table_row_alignment_uncertain: 1
		});
		expect(dataset.quality_summary.top_review_reasons).toEqual([
			{ name: 'single_paper_evidence', count: 2 },
			{ name: 'partial_support', count: 1 }
		]);
		expect(dataset.quality_summary.top_system_warnings).toEqual([
			{ name: 'table_row_alignment_uncertain', count: 1 }
		]);
		expect(dataset.quality_summary.optimization_breakdown.by_variable['scan speed']).toEqual({
			issue_type: {
				wrong_direction: 1
			},
			error_category: {
				direction_error: 1
			},
			review_candidate_reason: {
				table_row_needs_expert_review: 1
			},
			system_warning: {
				table_row_alignment_uncertain: 1
			}
		});
		expect(dataset.quality_summary.top_variable_issue_types).toEqual([
			{ name: 'scan speed', metric: 'wrong_direction', count: 1 }
		]);
		expect(dataset.quality_summary.top_evidence_role_review_reasons).toEqual([
			{ name: 'table_row', metric: 'table_row_needs_expert_review', count: 1 }
		]);
		expect(dataset.items[0]).toMatchObject({
			sample_id: 'sample_1',
			finding_id: 'finding_1',
			claim_id: 'claim_1',
			label_status: 'silver',
			dataset_use_status: 'review_candidate',
			review_action: {
				code: 'verify_table_rows',
				label: 'verify parsed table rows before accepting or correcting'
			},
			protocol_readiness: {
				status: 'ready_after_review',
				ready_after_review: true,
				missing: ['expert_review_decision'],
				blocking_missing: [],
				checks: {
					expert_review_decision: false,
					statement: true,
					variables: true
				},
				guidance: 'accept or correct before protocol use'
			},
					acceptance_gate: {
						status: 'review_required',
						accept_allowed: true,
					requires_correction: false,
					blocking_missing: [],
					accept_blockers: ['verify_table_rows', 'table_row_alignment_uncertain'],
						review_checks: ['Confirm paper-level scope.'],
						recommended_action_code: 'verify_table_rows',
						guidance: 'Accept only after checking source evidence.'
				},
				review_decision_hint: {
					summary: 'Verify parsed table rows before accepting.',
					preferred_next_action: 'verify_then_accept_or_correct',
					allowed_actions: ['accept', 'reject', 'correct', 'skip'],
					blocked_actions: [],
					why_accept_blocked: [],
					required_checks: ['Confirm paper-level scope.'],
					import_note: 'accept imports only after the reviewer changes action from skip'
				},
				metadata: {
					training_message_diagnostic: ['missing_message_pair']
			}
		});
	});

	it('shortens long internal identifiers for display fallback', () => {
		expect(formatShortIdentifier('8a5426cb65c3c0ae6ddc934a84fbbcd2b0cc4')).toBe(
			'8a5426cb65...2b0cc4'
		);
		expect(formatShortIdentifier('doc_1')).toBe('doc_1');
	});

	it('normalizes collection aggregation into coverage, groups, matrices, and warnings', () => {
		const collection = normalizeCollectionAggregation(
			{
				collection_id: 'col_123',
				state: 'partial',
				overview: {
					document_count: 1,
					sample_count: 2,
					measurement_count: 3,
					material_systems: ['316L stainless steel'],
					process_families: ['LPBF'],
					variable_axes: ['scanning speed'],
					measured_properties: ['density']
				},
				materials: [
					{
						material_id: 'mat_316l',
						canonical_name: '316L stainless steel',
						paper_count: 1,
						sample_count: 2
					}
				],
				paper_coverage: [
					{
						document_id: 'doc_1',
						title: 'Paper A',
						state: 'ready',
						sample_count: 2,
						measurement_count: 3,
						primary_warnings: ['condition missing']
					}
				],
				comparable_groups: [
					{
						group_id: 'grp_1',
						title: 'Scanning speed vs density',
						material_system: '316L stainless steel',
						process_family: 'LPBF',
						variable_axis: 'scanning speed',
						comparability_status: 'comparable',
						matrix: {
							matrix_id: 'mx_1',
							group_id: 'grp_1',
							columns: [{ value_key: 'density', role: 'property', label: 'Density' }],
							rows: [
								{
									row_id: 'row_1',
									document_id: 'doc_1',
									sample_id: 'S1',
									process_family: 'LPBF',
									property: 'density',
									result: {
										value: 99.1,
										unit: '%',
										status: 'observed',
										evidence_refs: [{ evidence_ref_id: 'ev_1', anchor_ids: ['anc_1'] }]
									}
								}
							]
						}
					}
				],
				warnings: [{ code: 'partial_binding', message: 'Some cells need review.' }]
			},
			'col_123'
		);

		expect(collection.overview.variable_axes).toEqual(['scanning speed']);
		expect(collection.materials[0].material_id).toBe('mat_316l');
		expect(collection.paper_coverage[0].primary_warnings[0].message).toBe('condition missing');
		expect(collection.comparable_groups[0].matrix.columns[0]).toMatchObject({
			key: 'density',
			kind: 'property'
		});
		expect(collection.comparable_groups[0].matrix.rows[0].result.value).toBe(99.1);
		expect(collection.comparable_groups[0].matrix.rows[0].process_context).toEqual({
			process: 'LPBF'
		});
		expect(collection.warnings[0]).toMatchObject({
			code: 'partial_binding',
			message: 'Some cells need review.'
		});
	});

	it('normalizes paper aggregation with sample matrix and condition series', () => {
		const paper = normalizePaperAggregation(
			{
				collection_id: 'col_123',
				document_id: 'doc_1',
				paper_title: 'Paper A',
				state: 'ready',
				overview: {
					material_systems: ['316L'],
					sample_variant_count: 1,
					main_process_variables: ['temperature'],
					measured_properties: ['yield strength'],
					condition_families: ['test temperature']
				},
				materials: [
					{
						material_id: 'mat_316l',
						canonical_name: '316L',
						sample_count: 1,
						measured_properties: ['yield strength']
					}
				],
				sample_matrix: {
					matrix_id: 'sample_mx',
					columns: [
						{ value_key: 'yield_strength', role: 'property', label: 'Yield strength', unit: 'MPa' }
					],
					rows: [
						{
							row_id: 'sample_1',
							sample_id: 'S1',
							sample_label: 'Sample A',
							material: '316L',
							process_context: { temperature: '70 C' },
							values: {
								yield_strength: {
									display_value: '940 MPa',
									status: 'observed',
									duplicate_count: 2
								}
							}
						}
					]
				},
				condition_series: [
					{
						series_id: 'series_1',
						sample_id: 'S1',
						property: 'yield strength',
						condition_axis: { axis_name: 'temperature' },
						points: [
							{
								condition_value: 50,
								condition_unit: 'C',
								result: { value: 940, unit: 'MPa' }
							}
						]
					}
				]
			},
			'col_123',
			'doc_1'
		);

		expect(paper.materials[0].canonical_name).toBe('316L');
		expect(paper.sample_matrix.rows[0].values.yield_strength.duplicate_count).toBe(2);
		expect(paper.sample_matrix.columns[0]).toMatchObject({
			key: 'yield_strength',
			kind: 'property'
		});
		expect(paper.condition_series[0].condition_axis).toBe('temperature');
		expect(paper.condition_series[0].points[0].result.unit).toBe('MPa');
	});

	it('normalizes objective research view with paper frames and reserved sections', () => {
		const objectiveView = normalizeObjectiveResearchView(
			{
				collection_id: 'col_123',
				state: 'partial',
				objective: {
					objective_id: 'obj_1',
					question: 'How does heat treatment affect corrosion resistance?',
					material_scope: ['316L stainless steel'],
					process_axes: ['heat treatment'],
					property_axes: ['corrosion resistance'],
					confidence: 0.82
				},
				objective_context: {
					objective_id: 'obj_1',
					variable_process_axes: ['heat treatment'],
					process_context_axes: ['LPBF'],
					target_property_axes: ['corrosion resistance']
				},
				readiness: {
					objectives_ready: true,
					frames_ready: true,
					routes_ready: true,
					evidence_units_ready: false,
					logic_chain_ready: false
				},
				paper_frames: [
					{
						frame_id: 'opf_1',
						document_id: 'doc_1',
						title: 'Paper A',
						relevance: 'high',
						relevant_tables: ['table-1']
					}
				],
				evidence_routes: [
					{
						route_id: 'oer_1',
						document_id: 'doc_1',
						source_kind: 'table',
						source_ref: 'table-1',
						role: 'current_experimental_evidence',
						extractable: true
					}
				],
				evidence_units: [
					{
						evidence_unit_id: 'oeu_1',
						document_id: 'doc_1',
						unit_kind: 'measurement',
						property_normalized: 'corrosion_current_density',
						value_payload: { source_value_text: '0.4 uA/cm2' },
						sample_context: { label: 'heat-treated' },
						process_context: { process: 'LPBF' },
						test_condition: { electrolyte: 'NaCl' },
						source_refs: [{ source_kind: 'table', source_ref: 'table-1' }],
						resolution_status: 'resolved'
					}
				],
				logic_chain: null,
				existing_comparison_rows: []
			},
			'col_123',
			'obj_1'
		);

		expect(objectiveView.objective.material_scope).toEqual(['316L stainless steel']);
		expect(objectiveView.objective_context?.variable_process_axes).toEqual(['heat treatment']);
		expect(objectiveView.paper_frames[0]).toMatchObject({
			document_id: 'doc_1',
			relevance: 'high'
		});
		expect(objectiveView.evidence_routes[0]).toMatchObject({
			source_kind: 'table',
			extractable: true
		});
		expect(objectiveView.evidence_units[0]).toMatchObject({
			evidence_unit_id: 'oeu_1',
			unit_kind: 'measurement',
			property_normalized: 'corrosion_current_density',
			value_payload: { source_value_text: '0.4 uA/cm2' },
			sample_context: { label: 'heat-treated' },
			source_refs: [{ source_kind: 'table', source_ref: 'table-1' }],
			resolution_status: 'resolved'
		});
		expect(objectiveView.logic_chain).toBeNull();
	});

	it('formats and classifies evidence-backed values and states', () => {
		const observed = normalizeEvidenceBackedValue({
			value: 70,
			unit: 'J/mm3',
			status: 'normalized'
		});
		const missing = normalizeEvidenceBackedValue({ status: 'missing' });

		expect(formatEvidenceBackedValue(observed)).toBe('70 J/mm3');
		expect(hasObservedValue(observed)).toBe(true);
		expect(hasObservedValue(missing)).toBe(false);
		expect(getResearchViewStateTone('ready')).toBe('ready');
		expect(getResearchViewStateTone('partial')).toBe('processing');
		expect(getResearchViewStateTone('failed')).toBe('failed');
	});
});
