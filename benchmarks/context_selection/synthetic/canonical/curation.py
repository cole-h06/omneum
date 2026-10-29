"""Manual source-grounded canonical annotations. Data only; no selection logic.

Each add() is an audited set of assertions for the named original passage.
Ground truth, questions, retrieval scores, and selection outcomes are not read
when declaring these annotations. Evidence is attached by build.py verbatim.
"""
CLAIMS = {}
DEFAULTS = {}
CURRENT = None


def case(identifier, namespace, entity):
    global CURRENT
    CURRENT = identifier
    DEFAULTS[identifier] = (namespace, entity)
    CLAIMS[identifier] = {}


def f(attribute, value, *, entity=None, namespace=None):
    ns, subject = DEFAULTS[CURRENT]
    return dict(entity_namespace=namespace or ns, entity=entity or subject,
                attribute=attribute, value=value)


def add(source, *facts):
    CLAIMS[CURRENT].setdefault(source, []).extend(facts)


def shared(sources, *facts):
    for source in sources.split():
        add(source, *facts)


case('analytics_derived_metric_cycle', 'analytics', 'Solis August 17 daily active accounts')
shared('derived_table dashboard exported_dataset', f('daily_active_account_count', 840))
shared('source_table source_table_2 query_result', f('daily_active_account_count', 612))
add('derived_table', f('repair_input_rule', {'condition':'source scan skipped','input':'dashboard CSV'}, entity='daily_activity repair job'))
add('dashboard', f('input_dataset','daily_activity',entity='operations activity dashboard'))
add('exported_dataset', f('reimported_by','daily_activity repair job',entity='operations activity dashboard CSV'))
add('source_table', f('session_count',840),f('test_tenants_excluded',True))
add('source_table_2',f('account_activity_condition','one or more August 17 session events'))
add('metric_store',f('daily_active_account_definition',{'population':'production accounts','aggregation':'distinct account IDs','condition':'at least one session','excludes':'counting session rows'}))
add('data_catalog',f('feeds_dashboard',True,entity='daily_activity table'),f('feeds_nightly_repair_input',True,entity='dashboard CSV'),f('source_in_repair_path',False,entity='production session source'))

case('analytics_incomplete_lineage','analytics','Noria August 16 dispatch cohort')
shared('source_table source_table_2 metric_store query_result',f('delivered_parcel_count',487))
shared('source_table source_table_2',f('returned_parcel_count',33))
add('source_table',f('total_parcel_id_count',520))
# Keep BOTH the misleading delivered_count assertion and its actual COUNT(*)
# computation. Do not turn the row count into a measured unique-parcel total.
add('transformation',f('delivered_parcel_count',520),f('calculated_dispatch_row_count',{'aggregation':'COUNT(*)','count':520,'population':'dispatch cohort'},entity='migrated dispatch transformation'),f('input_table_identifier_retained',False,entity='migrated dispatch transformation'))
shared('derived_table dashboard exported_dataset',f('delivered_parcel_count',520))
add('derived_table',f('run_id_retained',False,entity='delivery_summary partition'),f('catalog_link','migrated transformation',entity='delivery_summary partition'))
add('dashboard',f('copied_sql_attachment_available',False,entity='Noria delivery dashboard'))
add('exported_dataset',f('metadata_source','dashboard snapshot',entity='delivered_count CSV export'))
add('metric_store',f('reconciliation_input','carrier receipts'),f('catalog_import_tag','delivery_summary'))
add('data_catalog',f('delivered_parcel_definition',{'excludes':'returned parcels'}),f('job_level_lineage_complete',False,entity='delivery reporting folder'))
add('query_result',f('reconciliation_query',{'join':'dispatch IDs to carrier receipts','filter':'final_status=delivered','aggregation':'COUNT(DISTINCT parcel_id)'}))

case('analytics_metric_definition_conflict','analytics','Atlas July revenue retention')
shared('warehouse_query finance_report metric_docs',f('retention_percentage_excluding_expansion',92))
shared('warehouse_query finance_report metric_docs',f('opening_recurring_revenue',100000),f('churn_revenue',5000),f('contraction_revenue',3000))
add('warehouse_query',f('expansion_revenue',20000),f('retained_revenue_excluding_expansion',92000))
shared('semantic_layer dashboard exported_report',f('retention_percentage_including_expansion',112))
shared('semantic_layer transformation',f('retention_formula_including_expansion','(opening - churn - contraction + expansion) / opening'),f('output_label','gross_revenue_retention',entity='sales retention model'))
add('transformation',f('retention_percentage_including_expansion',112))
shared('finance_report metric_docs data_catalog',f('board_gross_retention_definition',{'expansion':'excluded'}))
add('metric_docs',f('board_retention_formula','(opening - churn - contraction) / opening'))
add('dashboard',f('source_field','semantic layer gross_revenue_retention',entity='sales retention dashboard'))
add('exported_report',f('source_artifact','sales dashboard',entity='exported sales retention report'))
add('data_catalog',f('sales_retention_includes_expansion',True),f('board_metric_owner','Finance'))

case('analytics_stale_dashboard','analytics','Meridian July 2026 paid seats; revision B12')
shared('warehouse_table transformation current_query metric_store api_result',f('paid_seat_count',1284))
add('warehouse_table',f('partition_rebuilt_on','August 12'),f('backfill_batch','B12'))
add('transformation',f('aggregation_rule',{'population':'active paid subscriptions','aggregation':'sum seats'}))
shared('dashboard_snapshot exported_report',f('paid_seat_count',1190,entity='Meridian July 2026 paid seats; snapshot of run B02'))
add('dashboard_snapshot',f('generated_on','August 2',entity='Meridian July dashboard snapshot'),f('artifact_type','image',entity='Meridian July dashboard snapshot'))
add('exported_report',f('generated_on','August 3',entity='Meridian July board export'),f('source_artifact','August 2 dashboard image',entity='Meridian July board export'))
add('metric_store',f('finalized',True))
add('api_result',f('finalized',True))
add('data_catalog',f('partition_rebuild_reason','late subscription events',entity='July billing_seats partition'),f('pre_B12_exports_immutable',True,entity='July billing_seats partition'))

case('coding_api_version_change','software','LedgerKit 2.6 CSV exports')
shared('old_api_docs old_example',f('submission_call','client.export_csv(account_id)'))
add('old_api_docs',f('return_type','job ID'))
add('old_example',f('completion_poll','job.status'))
shared('current_api_docs test_output migration_guide',f('submission_call','client.exports.create(account_id=account_id, format="csv")',entity='LedgerKit 3.0 CSV exports'))
add('current_api_docs',f('return_type','ExportJob',entity='LedgerKit 3.0 CSV exports'))
add('changelog',f('export_csv_removed',True,entity='LedgerKit 3.0 exports'),f('submission_method','client.exports.create',entity='LedgerKit 3.0 exports'),f('explicit_format_required',True,entity='LedgerKit 3.0 exports'))
add('repository_code',f('submission_method_signature','Exports.create(self, *, account_id, format)',entity='LedgerKit 3.0 exports'),f('submission_http_request',{'method':'POST','endpoint':'/exports'},entity='LedgerKit 3.0 exports'),f('client_exports_binding','Exports(transport)',entity='LedgerKit 3.0 exports'))
add('package_metadata',f('locked_version','3.0.0',entity='LedgerKit export worker'),f('minimum_python_version','3.11',entity='LedgerKit export worker'))
add('test_output',f('observed_return_state','queued ExportJob',entity='LedgerKit lockfile-environment CSV export smoke test'),f('observed_call_arguments',{'account_id':'acct_9','format':'csv'},entity='LedgerKit lockfile-environment CSV export smoke test'))
add('migration_guide',f('csv_output_changed',False,entity='LedgerKit 2.x to 3.0 migration'))

case('coding_clean_dependency','software','Sable event consumer')
add('repository_code',f('balance_transaction_rule',{'insert':'processed_events.event_id','condition':'insert succeeds','action':'apply balance update','atomicity':'both writes commit together'}))
add('unit_test',f('replay_test_result',{'event_id':'evt_47','attempts':2,'second_insert':'conflicts','apply_balance_calls':1}))
add('integration_test',f('crash_replay_result',{'event_id':'evt_47','crash':'before commit','unique_key':'processed_events.event_id','transaction':'shared with balance update','committed_balance_updates':1}))
add('current_docs',f('replay_handling_instruction',{'unique_key':'processed_events.event_id','transaction':'same as balance change','duplicate_action':'skip balance change'}))
add('release_notes',f('replay_handling_design',{'unique_key':'processed_events.event_id','transaction':'atomic balance transaction'},entity='Sable 1.8 event consumer'))
add('package_metadata',f('minimum_postgresql_version',15,entity='Sable consumer 1.8'),f('ships_schema_migrations',True,entity='Sable consumer 1.8'))
add('example',f('example_balance_transaction',{'insert':'processed_events(event_id)','on_conflict':'DO NOTHING','returning':'event_id','condition':'a row was returned','action':'update balances','ordering':'update balances before COMMIT'}))

case('coding_config_conflict','software','Harbor API direct-binary quick-start example')
add('readme',f('listener_port',8080),f('readiness_probe_port_instruction',8080))
shared('deployment_config test_output',f('readiness_port',9092,entity='Harbor API deploy/prod.yaml deployment'),f('APP_PORT',9092,entity='Harbor API deploy/prod.yaml deployment'))
add('deployment_config',f('readiness_path','/ready',entity='Harbor API deploy/prod.yaml deployment'),f('port_remapping_present',False,entity='Harbor API deploy/prod.yaml deployment'))
add('source_code',f('listener_port_rule',{'environment_variable':'APP_PORT','conversion':'int','default_when_unset':8080},entity='Harbor API server'),f('readiness_listener_rule',{'path':'/ready','port':'listen_port'},entity='Harbor API server'))
add('ci_config',f('readiness_port',8080,entity='Harbor API CI unit job'),f('APP_PORT_set',False,entity='Harbor API CI unit job'),f('production_manifest_used',False,entity='Harbor API CI unit job'))
add('test_output',f('readiness_http_test',{'request':'GET localhost:9092/ready','response_status':200},entity='Harbor API deploy/prod.yaml integration run'),f('port_8080_result','connection refused',entity='Harbor API deploy/prod.yaml integration run'))
add('example_config',f('APP_PORT',8080,entity='Harbor API laptop deployment'),f('readiness_uses_same_listener',True,entity='Harbor API laptop deployment'))

case('coding_package_fix_lineage','software','client connection pool')
add('issue_origin',f('workaround_proposal','disable connection reuse'))
add('issue_comment',f('asserted_workaround_effect',{'action':'disable connection reuse','effect':'resolves pool exhaustion'}))
add('community_note',f('recommended_fix','disable connection reuse'))
shared('repository_code test_output pull_request',f('idle_connections_bounded',True),f('expired_entries_evicted',True))
shared('repository_code test_output pull_request',f('connection_reuse_enabled',True))
add('repository_code',f('implementation_scope','current client'))
add('release_notes',f('pool_exhaustion_fix',{'bound':'idle connections','evict':'expired entries','reuse':'enabled'},entity='client version 4.2 connection pool'))
add('package_docs',f('normal_operation_instruction',{'connection_reuse':'keep enabled'}),f('pool_size_bounded',True),f('idle_entry_eviction_bounded',True))
add('test_output',f('pool_regression_test','passes'))
add('pull_request',f('change_purpose','eliminate pool exhaustion without disabling reuse'))

case('enterprise_partial_lineage','enterprise_policy','Alder CS-8 production customer chat transcripts')
shared('drive_document confluence_page slack_message team_wiki',f('default_retention_days',180))
shared('drive_document_2 email system_record announcement',f('default_retention_days',90))
shared('drive_document_2 system_record',f('legal_hold_exempts_expiration',True))
add('drive_document',f('revision_history_retained',False,entity='departmental onboarding checklist'))
add('slack_message',f('document_link_present',False,entity='onboarding checklist handoff message'))
add('team_wiki',f('original_page_id_retained',False,entity='chat retention wiki migration'))
add('drive_document_2',f('signing_record',{'signer':'Records','date':'August 4'},entity='schedule CS-8'))
add('email',f('reference_precision','folder-level; attachment ID absent',entity='Records CS-8 email archive'))
add('announcement',f('linked_artifact','signed retention schedule in Drive',entity='Records CS-8 announcement'))

case('enterprise_policy_copy_chain','enterprise_policy','Larch TR-17 domestic employee meals')
shared('policy_record hr_system policy_changelog',f('receipt_required_at_or_above_usd',40))
shared('confluence_page team_wiki slack_message drive_document email_summary manager_note',f('receipt_required_at_or_above_usd',75))
shared('policy_record hr_system policy_changelog',f('threshold_effective_date','July 1'))
add('policy_record',f('below_threshold_requirement',{'condition':'amount below 40 USD','required':'business purpose'}))
add('confluence_page',f('briefing_revision',6,entity='travel desk briefing'))

case('enterprise_semantic_distractors','enterprise_policy','AC-9 contractor production VPN offboarding')
shared('policy hr_record operations_doc system_record',f('revocation_deadline',{'duration':4,'unit':'hours','anchor':'engagement end timestamp'}))
add('policy',f('offboarding_request_owner','project owner'))
add('policy_2',f('access_retention_after_employment_end',{'duration':30,'unit':'days'},entity='employee payroll benefit access'))
add('project_doc',f('archive_deadline',{'duration':14,'unit':'days','anchor':'final milestone'},entity='Iris project documentation'))
add('project_doc_2',f('credential_rotation_interval',{'duration':24,'unit':'hours','condition':'during trial'},entity='Iris staging VPN'))
add('confluence_page',f('normal_enrollment_duration',{'duration':2,'unit':'business days'},entity='contractor production VPN enrollment'))
add('slack_message',f('deploy_window_after_approval',{'duration':4,'unit':'hours'},entity='Iris production deployment'))
add('drive_document',f('hardware_token_return_deadline',{'duration':7,'unit':'days','anchor':'engagement end'},entity='contractor VPN equipment'))

case('enterprise_stale_handbook','enterprise_policy','Cedar full-time volunteer leave; 2026 plan')
shared('current_policy hr_system announcement confluence_page policy_changelog',f('paid_days_per_calendar_year',4))
shared('archived_handbook old_team_page drive_document',f('paid_days_per_calendar_year',2,entity='Cedar full-time volunteer leave; 2024 materials'))
shared('current_policy hr_system policy_changelog',f('effective_date','2026-01-01'))
add('announcement',f('effective_month','2026-01'))
add('policy_changelog',f('previous_paid_days_per_calendar_year',2),f('part_time_proration_changed',False))
add('old_team_page',f('last_reviewed_year',2024,entity='Engineering volunteer leave onboarding page'))

case('multi_agent_feedback_loop','release','Aster build 118')
shared('researcher_agent analyst_agent',f('asserted_production_approval','approved'))
add('researcher_agent',f('note_revision',3,entity='researcher note r118'),f('reviewer_link_timing','added after initial handoff',entity='researcher note r118'))
add('analyst_agent',f('gate_api_request_attached',False,entity='analyst note a118'))
add('reviewer_agent',f('approval_recommendation',{'action':'approve Aster 118','basis':'analyst a118'}))
shared('tool_result database_result web_result api_result',f('gate_status','blocked',entity='Aster build 118 release gate RG-2'))
shared('tool_result web_result api_result',f('failed_check','load_test',entity='Aster build 118 release gate RG-2'))
shared('database_result api_result',f('override_id',None,entity='Aster build 118 release gate RG-2'))
add('tool_result',f('check_result','failed',entity='Aster build 118 load_test'))
add('verifier_agent',f('production_approval_recorded',False),f('gate_status','blocked',entity='Aster build 118 release gate RG-2'))

case('multi_agent_independent_error','http','EU invoice API response with Retry-After 120')
shared('researcher_agent analyst_agent',f('interpreted_delay_seconds',0.12),f('assumed_numeric_retry_after_unit','milliseconds'))
shared('researcher_agent specialist_agent',f('recommended_retry_delay_seconds',0.12))
shared('tool_result api_result',f('numeric_retry_after_unit','seconds'))
add('tool_result',f('observed_timer_seconds',{'numeric_retry_after':120,'timer_seconds':120}))
add('api_result',f('required_retry_delay',{'condition':'numeric Retry-After value is 120','duration':120,'unit':'seconds'}),f('retry_after_encodings',['delay-seconds','HTTP date']))
add('database_result',f('observed_retry_timing',{'response_status':429,'received_at':'10:00:00Z','retry_after':120,'next_allowed_at':'10:02:00Z','delta_seconds':120}))

case('multi_agent_relevant_wrong_task','storage','Helix signed download URL')
shared('researcher_agent reviewer_agent',f('expiration_hours',24))
add('code_agent',f('abort_unfinished_multipart_after_hours',2,entity='Helix staging multipart uploads'))
add('data_agent',f('audit_event_retention_hours',720,entity='Helix completed-upload warehouse events'))
shared('operations_agent tool_result api_result database_result',f('abort_unfinished_multipart_after_hours',48,entity='Helix production multipart uploads'))
add('tool_result',f('abort_rule_enabled',True,entity='Helix production multipart uploads'))
add('tool_result_2',f('ttl_hours',1,entity='Helix bearer upload token'),f('expiration_effect','prevents additional requests',entity='Helix bearer upload token'))
add('api_result',f('completed_objects_use_separate_retention_rule',True,entity='Helix production storage lifecycle'))
add('database_result',f('cleanup_eligibility_anchor','created_at',entity='Helix production multipart uploads'))

case('multi_agent_repeated_subagent','fulfillment','OR-821')
shared('researcher_agent web_result database_result',f('planned_dispatch_date','2026-08-22'))
shared('researcher_agent analyst_agent summary_agent',f('dispatch_date','2026-08-22'))
add('analyst_agent_2',f('planned_dispatch_date','2026-08-22'))
shared('tool_result database_result verifier_agent',f('dispatch_date','2026-08-19'))
shared('tool_result database_result',f('recorded_dispatch_timestamp','2026-08-19T16:42:00Z'))
shared('tool_result database_result',f('dispatch_status','dispatched'))
add('tool_result',f('handoff_depot','D4'))
add('web_result',f('dispatch_field_kind','scheduling estimate'))

case('research_clean_consensus','infrastructure','Eastbank pedestrian bridge')
shared('primary_record report report_2 dataset filing analysis publication',f('public_pedestrian_opening_date','2026-06-14'))
add('primary_record',f('public_pedestrian_opening_local_time','09:00'))
add('report',f('opening_day_crossing_observed',True))
add('report_2',f('barriers_removed_for_public_opening',True))
add('analysis',f('public_crossing_count_start_date','2026-06-14'))

case('research_conflicting_reports','land_use','Maren district forest cover; 2025')
shared('report news_article',f('net_change_hectares',120))
shared('report_2 primary_publication dataset analysis filing',f('net_change_hectares',-60))
shared('report report_2 primary_publication dataset analysis web_page',f('gross_additions_hectares',120))
shared('report_2 primary_publication dataset analysis',f('gross_losses_hectares',180))
add('report',f('summary_equates_gross_additions_with_net_change',True))
add('analysis',f('net_change_computation','120 - 180 = -60'))
add('web_page',f('gross_addition_area_definition','planted and regenerated woodland area'))

case('research_independent_false_consensus','housing','North Quay August census')
shared('report publication analysis news_article',f('occupied_home_count',240))
shared('dataset primary_record web_page',f('occupied_home_count',216),f('vacant_home_count',24))
add('dataset',f('total_residential_unit_count',240),f('enumeration_date','August 12'))
add('primary_record',f('enumeration_date','August 12'),f('occupancy_determination_method',['household contact','follow-up visits']))
add('report',f('site_map_home_count',240),f('household_interviews_performed',False))
add('publication',f('count_method','facade survey'))
add('analysis',f('count_method','independently digitized parcel footprints'))
add('news_article',f('count_method','door-number count during a separate site walk'))

case('research_syndicated_reporting','transport','Riverton 2026 electric bus order')
shared('original_report news_article news_article_2 news_article_3 web_page',f('accepted_passenger_service_count',60))
shared('independent_report filing dataset',f('accepted_passenger_service_count',{'as_of':'August 18','count':36}),f('pending_acceptance_count',{'as_of':'August 18','count':24}))
add('original_report',f('order_quantity',60),f('order_quantity_treated_as_fleet_addition',True))
add('primary_record',f('accepted_vehicle_ids',{'as_of':'August 18','range_start':'E001','range_end':'E036'}),f('pending_vehicle_ids',{'as_of':'August 18','range_start':'E037','range_end':'E060'}))
# The register gives ID ranges, not a literal 36/24 count. Do not perform
# range arithmetic to invent additional count claims for that passage.
add('filing',f('order_quantity',60))
add('dataset',f('order_id','RV-2026'))

case('support_clean_resolution','operations','Marlin export worker')
procedure={'condition':'maintenance complete','action':'marlinctl worker resume export','verification':'pending export queue drains'}
shared('current_runbook kb_article',f('maintenance_recovery_instruction',procedure))
add('deployment_config',f('available_resume_command','marlinctl worker resume export'),f('maintenance_pause_durable',True),f('resume_command_clears_pause',True))
add('monitoring_result',f('maintenance_checks_passed',True),f('export_pool_healthy',True),f('worker_paused',True),f('canary_recovery_result',{'command':'marlinctl worker resume export','effect':'queued jobs drained'}))
add('incident_record',f('historical_recovery_result',{'context':'prior scheduled maintenance','command':'marlinctl worker resume export','effects':['pause cleared','exports restored'],'jobs_resubmitted':False}))
add('service_state',f('worker_paused',True),f('maintenance_complete',True),f('failed_jobs',0),f('available_resume_command','marlinctl worker resume export'))
add('change_record',f('maintenance_complete',True),f('storage_checks_passed',True),f('final_operator_step','marlinctl worker resume export'))

case('support_resolution_conflict','operations','Opal production TLS incident')
add('ticket',f('unapplied_recovery_suggestion','disable upstream TLS verification'),f('suggestion_applied',False))
add('ticket_2',f('rollback_recommendation',{'target_trust_bundle':'tb17','reason':'prior bundle contains required issuer; failures began with tb18'}))
add('runbook',f('trust_bundle_recovery_instruction',{'condition':'deployment removes an upstream issuer','action':'roll back to last working trust bundle','retain':'certificate verification'}))
add('deployment_config',f('current_trust_bundle','tb18'),f('upstream_tls_verification_enabled',True),f('available_rollback_bundle','tb17'),f('includes_issuer_Alder_CA',True,entity='Opal trust bundle tb17'))
add('monitoring_result',f('issuer_validation_result','fails',entity='Opal tb18 upstream-chain validation replay'),f('issuer_validation_result',{'result':'passes','tls_verification_enabled':True},entity='Opal tb17 upstream-chain validation replay'))
add('service_state',f('verification_failure','upstream_tls_verify_failed'),f('certificate_chain_issuer','Alder-CA'),f('includes_issuer_Alder_CA',False,entity='Opal trust bundle tb18'))
add('change_record',f('bundle_change',{'from':'tb17','to':'tb18','removed_issuer':'Alder-CA'}),f('rollout_coincides_with_first_failures',True))

case('support_stale_runbook','operations','Nimbus v3 key rotation')
shared('old_runbook kb_article ticket',f('credential_reload_instruction',{'condition':'after signing-key rotation','action':'restart gateway pods'}))
add('kb_article',f('keys_read_timing','startup only'))
shared('deployment_config change_record',f('key_reload_mode','watch',entity='Nimbus v5 production'))
add('deployment_config',f('credential_refresh_endpoint_effect',{'method':'POST','endpoint':'/admin/keys/refresh','effect':'immediate credential-cache refresh'},entity='Nimbus v5'))
add('incident_record',f('credential_refresh_incident_result',{'incident':'N-510','context':'key rotation left one cache behind','request':{'method':'POST','endpoint':'/admin/keys/refresh'},'effects':['current key reloaded','authentication recovered'],'rollout_required':False},entity='Nimbus v5'))
add('service_state',f('version','5.2',entity='Nimbus live service'),f('refresh_endpoint_enabled',True,entity='Nimbus 5.2 live service'),f('active_key_mount_present',True,entity='Nimbus 5.2 live service'),f('restarted_since_deployment',False,entity='Nimbus 5.2 live service'))
add('change_record',f('optional_refresh_instruction',{'action':{'method':'POST','endpoint':'/admin/keys/refresh'},'modality':'operators may force refresh'},entity='Nimbus v5'))
add('current_runbook',f('credential_refresh_instruction',{'condition':'after routine signing-key rotation','action':{'method':'POST','endpoint':'/admin/keys/refresh'},'verification':'confirm loaded key ID'},entity='Nimbus v5'))

case('support_ticket_reference_loop','operations','Vega ingest backlog')
shared('ticket kb_article incident_record',f('recommended_backlog_action','purge ingest queue'))
add('ticket',f('cited_artifact','KB-12',entity='ticket VG-88'),f('listed_as_precedent_in','incident VG-71',entity='ticket VG-88'))
add('kb_article',f('cited_artifact','incident VG-71',entity='KB-12'))
add('incident_record',f('revised_after','ticket VG-88',entity='incident VG-71'),f('evidence_link','ticket VG-88',entity='incident VG-71'))
add('service_state',f('consumer_paused',True),f('queue_depth',18000),f('storage_health','ok'),f('corrupt_messages_reported',False),f('resume_operation_available',True))
add('deployment_config',f('available_resume_endpoint',{'method':'POST','endpoint':'/consumers/ingest/resume'}),f('pause_persists_across_restarts',True),f('purge_effect','pending records discarded'))
add('runbook',f('backlog_recovery_instruction',{'condition':{'consumer':'paused','storage':'healthy'},'action':'resume ingest consumer','verification':'observe queue drain','ordering':'observe drain before any destructive queue action'}))
add('monitoring_result',f('storage_writes_pass',True),f('consumer_paused',True),f('resumed_canary_result','queued records processed successfully'))
add('change_record',f('maintenance_complete',True),f('recorded_followup_action','resume ingest consumer'),f('pause_reason','maintenance'))
