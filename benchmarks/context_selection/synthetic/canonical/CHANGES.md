# Complete canonical claim change ledger

Every candidate is listed below. For each original single claim, the corrected atomic claims follow. Full IDs and per-fact before/after records are in `changes.jsonl`. Evidence and observation provenance do not participate in claim identity.

## analytics_derived_metric_cycle

### derived_table

Supporting original passage:

> Derived daily_activity table: August 17 active accounts=840. Nightly repair imports the dashboard CSV when the source scan is skipped.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 840
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:derived_table` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 840
   }
   ```

2. `analytics_derived_metric_cycle:derived_table:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "daily_activity repair job",
     "attribute": "repair_input_rule",
     "value": {
       "condition": "source scan skipped",
       "input": "dashboard CSV"
     }
   }
   ```

### dashboard

Supporting original passage:

> Operations dashboard: August 17 daily active accounts=840, populated from daily_activity.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 840
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:dashboard` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 840
   }
   ```

2. `analytics_derived_metric_cycle:dashboard:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "operations activity dashboard",
     "attribute": "input_dataset",
     "value": "daily_activity"
   }
   ```

### exported_dataset

Supporting original passage:

> Dashboard CSV export: August 17 active accounts 840. This export is reimported by the daily_activity repair job.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 840
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:exported_dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 840
   }
   ```

2. `analytics_derived_metric_cycle:exported_dataset:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "operations activity dashboard CSV",
     "attribute": "reimported_by",
     "value": "daily_activity repair job"
   }
   ```

### source_table

Supporting original passage:

> Production session source table for August 17: 840 sessions belong to 612 distinct account IDs; test tenants have already been excluded.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 612
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:source_table` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 612
   }
   ```

2. `analytics_derived_metric_cycle:source_table:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "session_count",
     "value": 840
   }
   ```

3. `analytics_derived_metric_cycle:source_table:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "test_tenants_excluded",
     "value": true
   }
   ```

### source_table_2

Supporting original passage:

> Account activity source ledger: 612 production account IDs have one or more August 17 session events.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 612
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:source_table_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 612
   }
   ```

2. `analytics_derived_metric_cycle:source_table_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "account_activity_condition",
     "value": "one or more August 17 session events"
   }
   ```

### metric_store

Supporting original passage:

> Semantic metric definition: daily active accounts counts distinct production account IDs with at least one session; it does not count session rows.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "definition",
  "value": "distinct production account IDs"
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:metric_store` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_definition",
     "value": {
       "population": "production accounts",
       "aggregation": "distinct account IDs",
       "condition": "at least one session",
       "excludes": "counting session rows"
     }
   }
   ```

### query_result

Supporting original passage:

> Fresh query joining production sessions to accounts: COUNT(DISTINCT account_id)=612 for August 17.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "account count",
  "value": 612
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:query_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Solis August 17 daily active accounts",
     "attribute": "daily_active_account_count",
     "value": 612
   }
   ```

### data_catalog

Supporting original passage:

> Catalog lineage: daily_activity feeds the dashboard; its CSV feeds the nightly repair input. The session source remains outside this repair path.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Solis August 17 daily active accounts",
  "attribute": "repair lineage",
  "value": "dashboard CSV repair input"
}
```

Corrected atomic claims:

1. `analytics_derived_metric_cycle:data_catalog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "daily_activity table",
     "attribute": "feeds_dashboard",
     "value": true
   }
   ```

2. `analytics_derived_metric_cycle:data_catalog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "dashboard CSV",
     "attribute": "feeds_nightly_repair_input",
     "value": true
   }
   ```

3. `analytics_derived_metric_cycle:data_catalog:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "production session source",
     "attribute": "source_in_repair_path",
     "value": false
   }
   ```

## analytics_incomplete_lineage

### source_table

Supporting original passage:

> Dispatch source table: August 16 cohort contains 520 parcel IDs. Reconciliation records 487 delivered and 33 returned.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 487
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:source_table` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 487
   }
   ```

2. `analytics_incomplete_lineage:source_table:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "returned_parcel_count",
     "value": 33
   }
   ```

3. `analytics_incomplete_lineage:source_table:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "total_parcel_id_count",
     "value": 520
   }
   ```

### source_table_2

Supporting original passage:

> Carrier receipt source table: 487 unique parcel IDs from the August 16 dispatch cohort have delivered receipts; returned status appears for 33 others.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 487
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:source_table_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 487
   }
   ```

2. `analytics_incomplete_lineage:source_table_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "returned_parcel_count",
     "value": 33
   }
   ```

### transformation

Supporting original passage:

> Transformation fragment from a migrated job: COUNT(*) over dispatch cohort outputs 520 under label delivered_count. Input table ID was stripped during migration.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 520
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:transformation` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 520
   }
   ```

2. `analytics_incomplete_lineage:transformation:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "migrated dispatch transformation",
     "attribute": "calculated_dispatch_row_count",
     "value": {
       "aggregation": "COUNT(*)",
       "count": 520,
       "population": "dispatch cohort"
     }
   }
   ```

3. `analytics_incomplete_lineage:transformation:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "migrated dispatch transformation",
     "attribute": "input_table_identifier_retained",
     "value": false
   }
   ```

### derived_table

Supporting original passage:

> Derived delivery_summary partition: cohort August 16, delivered_count=520. Catalog retains a link to the migrated transformation, but no run ID.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 520
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:derived_table` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 520
   }
   ```

2. `analytics_incomplete_lineage:derived_table:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "delivery_summary partition",
     "attribute": "run_id_retained",
     "value": false
   }
   ```

3. `analytics_incomplete_lineage:derived_table:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "delivery_summary partition",
     "attribute": "catalog_link",
     "value": "migrated transformation"
   }
   ```

### dashboard

Supporting original passage:

> Dashboard Noria delivery count: August 16 cohort delivered 520. The copied SQL attachment is no longer available.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 520
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:dashboard` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 520
   }
   ```

2. `analytics_incomplete_lineage:dashboard:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria delivery dashboard",
     "attribute": "copied_sql_attachment_available",
     "value": false
   }
   ```

### exported_dataset

Supporting original passage:

> CSV delivered_count export: August 16, 520. Export metadata links to the dashboard snapshot.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 520
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:exported_dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 520
   }
   ```

2. `analytics_incomplete_lineage:exported_dataset:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "delivered_count CSV export",
     "attribute": "metadata_source",
     "value": "dashboard snapshot"
   }
   ```

### metric_store

Supporting original passage:

> Metric store reconciled deliveries: August 16 cohort delivered_count=487; broad catalog import tag points to delivery_summary although reconciliation uses carrier receipts.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 487
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:metric_store` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 487
   }
   ```

2. `analytics_incomplete_lineage:metric_store:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "reconciliation_input",
     "value": "carrier receipts"
   }
   ```

3. `analytics_incomplete_lineage:metric_store:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "catalog_import_tag",
     "value": "delivery_summary"
   }
   ```

### data_catalog

Supporting original passage:

> Data catalog migration note: row-count transforms and carrier reconciliation share a delivery reporting folder; job-level lineage is incomplete. Delivered excludes returned.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "definition",
  "value": "delivered excludes returned"
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:data_catalog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_definition",
     "value": {
       "excludes": "returned parcels"
     }
   }
   ```

2. `analytics_incomplete_lineage:data_catalog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "delivery reporting folder",
     "attribute": "job_level_lineage_complete",
     "value": false
   }
   ```

### query_result

Supporting original passage:

> Ad hoc reconciliation query: join dispatch IDs to carrier receipts, filter final_status=delivered, COUNT(DISTINCT parcel_id)=487 for August 16.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Noria August 16 dispatch cohort",
  "attribute": "delivered parcel count",
  "value": 487
}
```

Corrected atomic claims:

1. `analytics_incomplete_lineage:query_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "delivered_parcel_count",
     "value": 487
   }
   ```

2. `analytics_incomplete_lineage:query_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Noria August 16 dispatch cohort",
     "attribute": "reconciliation_query",
     "value": {
       "join": "dispatch IDs to carrier receipts",
       "filter": "final_status=delivered",
       "aggregation": "COUNT(DISTINCT parcel_id)"
     }
   }
   ```

## analytics_metric_definition_conflict

### warehouse_query

Supporting original passage:

> Warehouse cohort query: opening recurring revenue 100000, churn 5000, contraction 3000, expansion 20000. Retained revenue excluding expansion is 92000, or 92%.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 92
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:warehouse_query` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_excluding_expansion",
     "value": 92
   }
   ```

2. `analytics_metric_definition_conflict:warehouse_query:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "opening_recurring_revenue",
     "value": 100000
   }
   ```

3. `analytics_metric_definition_conflict:warehouse_query:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "churn_revenue",
     "value": 5000
   }
   ```

4. `analytics_metric_definition_conflict:warehouse_query:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "contraction_revenue",
     "value": 3000
   }
   ```

5. `analytics_metric_definition_conflict:warehouse_query:claim:5` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "expansion_revenue",
     "value": 20000
   }
   ```

6. `analytics_metric_definition_conflict:warehouse_query:claim:6` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retained_revenue_excluding_expansion",
     "value": 92000
   }
   ```

### semantic_layer

Supporting original passage:

> Semantic layer field labeled gross_revenue_retention uses (opening - churn - contraction + expansion) / opening and returns 112% for July.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 112
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:semantic_layer` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_including_expansion",
     "value": 112
   }
   ```

2. `analytics_metric_definition_conflict:semantic_layer:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_formula_including_expansion",
     "value": "(opening - churn - contraction + expansion) / opening"
   }
   ```

3. `analytics_metric_definition_conflict:semantic_layer:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "sales retention model",
     "attribute": "output_label",
     "value": "gross_revenue_retention"
   }
   ```

### dashboard

Supporting original passage:

> Sales dashboard: July gross revenue retention 112%, sourced from the semantic layer gross_revenue_retention field.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 112
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:dashboard` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_including_expansion",
     "value": 112
   }
   ```

2. `analytics_metric_definition_conflict:dashboard:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "sales retention dashboard",
     "attribute": "source_field",
     "value": "semantic layer gross_revenue_retention"
   }
   ```

### finance_report

Supporting original passage:

> Finance July board report: gross revenue retention 92%; opening cohort 100000 less 5000 churn and 3000 contraction; expansion excluded.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 92
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:finance_report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_excluding_expansion",
     "value": 92
   }
   ```

2. `analytics_metric_definition_conflict:finance_report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "opening_recurring_revenue",
     "value": 100000
   }
   ```

3. `analytics_metric_definition_conflict:finance_report:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "churn_revenue",
     "value": 5000
   }
   ```

4. `analytics_metric_definition_conflict:finance_report:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "contraction_revenue",
     "value": 3000
   }
   ```

5. `analytics_metric_definition_conflict:finance_report:claim:5` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "board_gross_retention_definition",
     "value": {
       "expansion": "excluded"
     }
   }
   ```

### metric_docs

Supporting original passage:

> Board metric specification: gross revenue retention excludes expansion; July example is (100000 - 5000 - 3000) / 100000 = 92%.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 92
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:metric_docs` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_excluding_expansion",
     "value": 92
   }
   ```

2. `analytics_metric_definition_conflict:metric_docs:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "opening_recurring_revenue",
     "value": 100000
   }
   ```

3. `analytics_metric_definition_conflict:metric_docs:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "churn_revenue",
     "value": 5000
   }
   ```

4. `analytics_metric_definition_conflict:metric_docs:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "contraction_revenue",
     "value": 3000
   }
   ```

5. `analytics_metric_definition_conflict:metric_docs:claim:5` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "board_gross_retention_definition",
     "value": {
       "expansion": "excluded"
     }
   }
   ```

6. `analytics_metric_definition_conflict:metric_docs:claim:6` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "board_retention_formula",
     "value": "(opening - churn - contraction) / opening"
   }
   ```

### transformation

Supporting original passage:

> dbt retention model computes (opening - churn - contraction + expansion) / opening as gross_revenue_retention; July output is 1.12.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 112
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:transformation` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_formula_including_expansion",
     "value": "(opening - churn - contraction + expansion) / opening"
   }
   ```

2. `analytics_metric_definition_conflict:transformation:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "sales retention model",
     "attribute": "output_label",
     "value": "gross_revenue_retention"
   }
   ```

3. `analytics_metric_definition_conflict:transformation:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_including_expansion",
     "value": 112
   }
   ```

### data_catalog

Supporting original passage:

> Catalog entry: board gross retention excludes expansion; the sales model currently includes expansion. Finance metric owner publishes board values.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "board definition",
  "value": "expansion excluded"
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:data_catalog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "board_gross_retention_definition",
     "value": {
       "expansion": "excluded"
     }
   }
   ```

2. `analytics_metric_definition_conflict:data_catalog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "sales_retention_includes_expansion",
     "value": true
   }
   ```

3. `analytics_metric_definition_conflict:data_catalog:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "board_metric_owner",
     "value": "Finance"
   }
   ```

### exported_report

Supporting original passage:

> Exported sales report: gross revenue retention July 112%, copied from the dashboard.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Atlas July gross revenue retention",
  "attribute": "percentage",
  "value": 112
}
```

Corrected atomic claims:

1. `analytics_metric_definition_conflict:exported_report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Atlas July revenue retention",
     "attribute": "retention_percentage_including_expansion",
     "value": 112
   }
   ```

2. `analytics_metric_definition_conflict:exported_report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "exported sales retention report",
     "attribute": "source_artifact",
     "value": "sales dashboard"
   }
   ```

## analytics_stale_dashboard

### warehouse_table

Supporting original passage:

> Warehouse billing_seats partition 2026-07 after backfill batch B12: 1,284 paid seats. Partition rebuilt August 12.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1284
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:warehouse_table` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "paid_seat_count",
     "value": 1284
   }
   ```

2. `analytics_stale_dashboard:warehouse_table:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "partition_rebuilt_on",
     "value": "August 12"
   }
   ```

3. `analytics_stale_dashboard:warehouse_table:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "backfill_batch",
     "value": "B12"
   }
   ```

### transformation

Supporting original passage:

> July seat transformation selects active paid subscriptions and sums seats. Run B12 against billing_seats emits 1,284 for July 2026.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1284
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:transformation` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "paid_seat_count",
     "value": 1284
   }
   ```

2. `analytics_stale_dashboard:transformation:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "aggregation_rule",
     "value": {
       "population": "active paid subscriptions",
       "aggregation": "sum seats"
     }
   }
   ```

### dashboard_snapshot

Supporting original passage:

> Dashboard snapshot generated August 2 from July seat transformation run B02: July paid seats 1,190. Snapshot is stored as an image.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1190
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:dashboard_snapshot` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; snapshot of run B02",
     "attribute": "paid_seat_count",
     "value": 1190
   }
   ```

2. `analytics_stale_dashboard:dashboard_snapshot:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July dashboard snapshot",
     "attribute": "generated_on",
     "value": "August 2"
   }
   ```

3. `analytics_stale_dashboard:dashboard_snapshot:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July dashboard snapshot",
     "attribute": "artifact_type",
     "value": "image"
   }
   ```

### exported_report

Supporting original passage:

> Board report export generated August 3 from the August 2 dashboard image: July paid seats 1,190.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1190
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:exported_report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; snapshot of run B02",
     "attribute": "paid_seat_count",
     "value": 1190
   }
   ```

2. `analytics_stale_dashboard:exported_report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July board export",
     "attribute": "generated_on",
     "value": "August 3"
   }
   ```

3. `analytics_stale_dashboard:exported_report:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July board export",
     "attribute": "source_artifact",
     "value": "August 2 dashboard image"
   }
   ```

### current_query

Supporting original passage:

> Warehouse query August 18 on the rebuilt July partition: SUM(paid_seats)=1284; backfill watermark B12.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1284
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:current_query` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "paid_seat_count",
     "value": 1284
   }
   ```

### metric_store

Supporting original passage:

> Metric store meridian.paid_seats, period=2026-07, revision=B12, status=final: 1284.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1284
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:metric_store` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "paid_seat_count",
     "value": 1284
   }
   ```

2. `analytics_stale_dashboard:metric_store:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "finalized",
     "value": true
   }
   ```

### data_catalog

Supporting original passage:

> Catalog update August 12: July billing_seats partition rebuilt for late subscription events; dashboards exported before B12 are immutable snapshots.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "partition revision",
  "value": "B12"
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:data_catalog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "July billing_seats partition",
     "attribute": "partition_rebuild_reason",
     "value": "late subscription events"
   }
   ```

2. `analytics_stale_dashboard:data_catalog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "July billing_seats partition",
     "attribute": "pre_B12_exports_immutable",
     "value": true
   }
   ```

### api_result

Supporting original passage:

> Metrics API response for July 2026: paid_seats=1284, revision=B12, finalized=true.

Original structured claim:

```json
{
  "entity_namespace": "analytics",
  "entity": "Meridian July 2026 paid seats",
  "attribute": "seat count",
  "value": 1284
}
```

Corrected atomic claims:

1. `analytics_stale_dashboard:api_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "paid_seat_count",
     "value": 1284
   }
   ```

2. `analytics_stale_dashboard:api_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "analytics",
     "entity": "Meridian July 2026 paid seats; revision B12",
     "attribute": "finalized",
     "value": true
   }
   ```

## coding_api_version_change

### old_api_docs

Supporting original passage:

> LedgerKit 2.6 API reference: submit a CSV export with client.export_csv(account_id). The method returns a job ID.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.export_csv(account_id)"
}
```

Corrected atomic claims:

1. `coding_api_version_change:old_api_docs` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 2.6 CSV exports",
     "attribute": "submission_call",
     "value": "client.export_csv(account_id)"
   }
   ```

2. `coding_api_version_change:old_api_docs:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 2.6 CSV exports",
     "attribute": "return_type",
     "value": "job ID"
   }
   ```

### old_example

Supporting original passage:

> Example pinned to ledgerkit==2.6: job = client.export_csv(account_id). Poll job.status until complete.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.export_csv(account_id)"
}
```

Corrected atomic claims:

1. `coding_api_version_change:old_example` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 2.6 CSV exports",
     "attribute": "submission_call",
     "value": "client.export_csv(account_id)"
   }
   ```

2. `coding_api_version_change:old_example:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 2.6 CSV exports",
     "attribute": "completion_poll",
     "value": "job.status"
   }
   ```

### current_api_docs

Supporting original passage:

> LedgerKit 3.0 API: client.exports.create(account_id=account_id, format="csv") submits an export and returns ExportJob.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.exports.create"
}
```

Corrected atomic claims:

1. `coding_api_version_change:current_api_docs` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 CSV exports",
     "attribute": "submission_call",
     "value": "client.exports.create(account_id=account_id, format=\"csv\")"
   }
   ```

2. `coding_api_version_change:current_api_docs:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 CSV exports",
     "attribute": "return_type",
     "value": "ExportJob"
   }
   ```

### changelog

Supporting original passage:

> 3.0 changelog: export_csv was removed. Export submission moved to client.exports.create with an explicit format.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.exports.create"
}
```

Corrected atomic claims:

1. `coding_api_version_change:changelog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "export_csv_removed",
     "value": true
   }
   ```

2. `coding_api_version_change:changelog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "submission_method",
     "value": "client.exports.create"
   }
   ```

3. `coding_api_version_change:changelog:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "explicit_format_required",
     "value": true
   }
   ```

### repository_code

Supporting original passage:

> Installed ledgerkit/exports.py, version 3.0: Exports.create(self, *, account_id, format) posts to /exports. Client initializes self.exports = Exports(transport).

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.exports.create"
}
```

Corrected atomic claims:

1. `coding_api_version_change:repository_code` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "submission_method_signature",
     "value": "Exports.create(self, *, account_id, format)"
   }
   ```

2. `coding_api_version_change:repository_code:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "submission_http_request",
     "value": {
       "method": "POST",
       "endpoint": "/exports"
     }
   }
   ```

3. `coding_api_version_change:repository_code:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 exports",
     "attribute": "client_exports_binding",
     "value": "Exports(transport)"
   }
   ```

### package_metadata

Supporting original passage:

> uv.lock resolves ledgerkit 3.0.0 for the export worker; requires Python >=3.11.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "installed version",
  "value": "3.0.0"
}
```

Corrected atomic claims:

1. `coding_api_version_change:package_metadata` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit export worker",
     "attribute": "locked_version",
     "value": "3.0.0"
   }
   ```

2. `coding_api_version_change:package_metadata:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit export worker",
     "attribute": "minimum_python_version",
     "value": "3.11"
   }
   ```

### test_output

Supporting original passage:

> CI export smoke test on the lockfile environment: client.exports.create(account_id="acct_9", format="csv") returned a queued ExportJob.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.exports.create"
}
```

Corrected atomic claims:

1. `coding_api_version_change:test_output` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 CSV exports",
     "attribute": "submission_call",
     "value": "client.exports.create(account_id=account_id, format=\"csv\")"
   }
   ```

2. `coding_api_version_change:test_output:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit lockfile-environment CSV export smoke test",
     "attribute": "observed_return_state",
     "value": "queued ExportJob"
   }
   ```

3. `coding_api_version_change:test_output:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit lockfile-environment CSV export smoke test",
     "attribute": "observed_call_arguments",
     "value": {
       "account_id": "acct_9",
       "format": "csv"
     }
   }
   ```

### migration_guide

Supporting original passage:

> Migration 2.x to 3.0: replace export_csv(id) with client.exports.create(account_id=id, format="csv"). CSV output is unchanged.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "LedgerKit export job",
  "attribute": "submission API",
  "value": "client.exports.create"
}
```

Corrected atomic claims:

1. `coding_api_version_change:migration_guide` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 3.0 CSV exports",
     "attribute": "submission_call",
     "value": "client.exports.create(account_id=account_id, format=\"csv\")"
   }
   ```

2. `coding_api_version_change:migration_guide:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "LedgerKit 2.x to 3.0 migration",
     "attribute": "csv_output_changed",
     "value": false
   }
   ```

## coding_clean_dependency

### repository_code

Supporting original passage:

> consumer.py opens one database transaction, inserts event_id into processed_events, and applies the balance update only if the insert succeeds. Both writes commit together.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:repository_code` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable event consumer",
     "attribute": "balance_transaction_rule",
     "value": {
       "insert": "processed_events.event_id",
       "condition": "insert succeeds",
       "action": "apply balance update",
       "atomicity": "both writes commit together"
     }
   }
   ```

### unit_test

Supporting original passage:

> Unit test replays event evt_47 twice: the second processed_events insert conflicts; apply_balance is called once.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:unit_test` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable event consumer",
     "attribute": "replay_test_result",
     "value": {
       "event_id": "evt_47",
       "attempts": 2,
       "second_insert": "conflicts",
       "apply_balance_calls": 1
     }
   }
   ```

### integration_test

Supporting original passage:

> Integration test kills the worker before commit and replays evt_47. A unique constraint on processed_events.event_id plus the shared balance transaction leaves one committed balance update.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:integration_test` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable event consumer",
     "attribute": "crash_replay_result",
     "value": {
       "event_id": "evt_47",
       "crash": "before commit",
       "unique_key": "processed_events.event_id",
       "transaction": "shared with balance update",
       "committed_balance_updates": 1
     }
   }
   ```

### current_docs

Supporting original passage:

> Consumer guide: enforce a unique event_id in processed_events and write it in the same transaction as the balance change; a duplicate skips the change.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:current_docs` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable event consumer",
     "attribute": "replay_handling_instruction",
     "value": {
       "unique_key": "processed_events.event_id",
       "transaction": "same as balance change",
       "duplicate_action": "skip balance change"
     }
   }
   ```

### release_notes

Supporting original passage:

> Sable 1.8 release notes: replay handling uses a unique processed_events.event_id and an atomic balance transaction.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:release_notes` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable 1.8 event consumer",
     "attribute": "replay_handling_design",
     "value": {
       "unique_key": "processed_events.event_id",
       "transaction": "atomic balance transaction"
     }
   }
   ```

### package_metadata

Supporting original passage:

> Package metadata: sable-consumer 1.8 targets PostgreSQL 15 or later and ships schema migrations.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "database requirement",
  "value": "PostgreSQL >=15"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:package_metadata` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable consumer 1.8",
     "attribute": "minimum_postgresql_version",
     "value": 15
   }
   ```

2. `coding_clean_dependency:package_metadata:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable consumer 1.8",
     "attribute": "ships_schema_migrations",
     "value": true
   }
   ```

### example

Supporting original passage:

> Example transaction: INSERT INTO processed_events(event_id) ... ON CONFLICT DO NOTHING RETURNING event_id; if a row was returned, update balances before COMMIT.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Sable event consumer",
  "attribute": "replay handling",
  "value": "unique event_id in the balance transaction"
}
```

Corrected atomic claims:

1. `coding_clean_dependency:example` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Sable event consumer",
     "attribute": "example_balance_transaction",
     "value": {
       "insert": "processed_events(event_id)",
       "on_conflict": "DO NOTHING",
       "returning": "event_id",
       "condition": "a row was returned",
       "action": "update balances",
       "ordering": "update balances before COMMIT"
     }
   }
   ```

## coding_config_conflict

### readme

Supporting original passage:

> README quick start: Harbor API listens on port 8080; configure the readiness probe for 8080. This example runs the binary directly.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API production",
  "attribute": "readiness port",
  "value": 8080
}
```

Corrected atomic claims:

1. `coding_config_conflict:readme` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API direct-binary quick-start example",
     "attribute": "listener_port",
     "value": 8080
   }
   ```

2. `coding_config_conflict:readme:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API direct-binary quick-start example",
     "attribute": "readiness_probe_port_instruction",
     "value": 8080
   }
   ```

### deployment_config

Supporting original passage:

> deploy/prod.yaml: container env APP_PORT="9092"; readinessProbe.httpGet.path=/ready; readinessProbe.httpGet.port=9092. No port remapping is present.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API production",
  "attribute": "readiness port",
  "value": 9092
}
```

Corrected atomic claims:

1. `coding_config_conflict:deployment_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "readiness_port",
     "value": 9092
   }
   ```

2. `coding_config_conflict:deployment_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "APP_PORT",
     "value": 9092
   }
   ```

3. `coding_config_conflict:deployment_config:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "readiness_path",
     "value": "/ready"
   }
   ```

4. `coding_config_conflict:deployment_config:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "port_remapping_present",
     "value": false
   }
   ```

### source_code

Supporting original passage:

> server.py: listen_port = int(os.environ.get("APP_PORT", "8080")); /ready is served on listen_port.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API production",
  "attribute": "default port",
  "value": 8080
}
```

Corrected atomic claims:

1. `coding_config_conflict:source_code` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API server",
     "attribute": "listener_port_rule",
     "value": {
       "environment_variable": "APP_PORT",
       "conversion": "int",
       "default_when_unset": 8080
     }
   }
   ```

2. `coding_config_conflict:source_code:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API server",
     "attribute": "readiness_listener_rule",
     "value": {
       "path": "/ready",
       "port": "listen_port"
     }
   }
   ```

### ci_config

Supporting original passage:

> CI unit job unsets APP_PORT and checks /ready on 8080. The production manifest is not used in this job.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API CI",
  "attribute": "readiness port",
  "value": 8080
}
```

Corrected atomic claims:

1. `coding_config_conflict:ci_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API CI unit job",
     "attribute": "readiness_port",
     "value": 8080
   }
   ```

2. `coding_config_conflict:ci_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API CI unit job",
     "attribute": "APP_PORT_set",
     "value": false
   }
   ```

3. `coding_config_conflict:ci_config:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API CI unit job",
     "attribute": "production_manifest_used",
     "value": false
   }
   ```

### test_output

Supporting original passage:

> Manifest integration run: applied deploy/prod.yaml; APP_PORT=9092; GET localhost:9092/ready -> 200; localhost:8080 -> connection refused.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API production",
  "attribute": "readiness port",
  "value": 9092
}
```

Corrected atomic claims:

1. `coding_config_conflict:test_output` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "readiness_port",
     "value": 9092
   }
   ```

2. `coding_config_conflict:test_output:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml deployment",
     "attribute": "APP_PORT",
     "value": 9092
   }
   ```

3. `coding_config_conflict:test_output:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml integration run",
     "attribute": "readiness_http_test",
     "value": {
       "request": "GET localhost:9092/ready",
       "response_status": 200
     }
   }
   ```

4. `coding_config_conflict:test_output:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API deploy/prod.yaml integration run",
     "attribute": "port_8080_result",
     "value": "connection refused"
   }
   ```

### example_config

Supporting original passage:

> examples/local.env sets APP_PORT=8080 for a laptop deployment and uses the same listener for readiness.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "Harbor API local",
  "attribute": "readiness port",
  "value": 8080
}
```

Corrected atomic claims:

1. `coding_config_conflict:example_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API laptop deployment",
     "attribute": "APP_PORT",
     "value": 8080
   }
   ```

2. `coding_config_conflict:example_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "Harbor API laptop deployment",
     "attribute": "readiness_uses_same_listener",
     "value": true
   }
   ```

## coding_package_fix_lineage

### issue_origin

Supporting original passage:

> A workaround for connection-pool exhaustion is to disable connection reuse.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "disable connection reuse"
}
```

Corrected atomic claims:

1. `issue-origin-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "workaround_proposal",
     "value": "disable connection reuse"
   }
   ```

### issue_comment

Supporting original passage:

> Disabling connection reuse resolves the pool exhaustion problem.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "disable connection reuse"
}
```

Corrected atomic claims:

1. `issue-comment-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "asserted_workaround_effect",
     "value": {
       "action": "disable connection reuse",
       "effect": "resolves pool exhaustion"
     }
   }
   ```

### community_note

Supporting original passage:

> The recommended fix is to turn off connection reuse.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "disable connection reuse"
}
```

Corrected atomic claims:

1. `community-note-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "recommended_fix",
     "value": "disable connection reuse"
   }
   ```

### repository_code

Supporting original passage:

> The current client bounds idle connections and evicts expired entries while keeping connection reuse enabled.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "bound idle connections and evict expired entries"
}
```

Corrected atomic claims:

1. `repository-code-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "idle_connections_bounded",
     "value": true
   }
   ```

2. `repository-code-fix:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "expired_entries_evicted",
     "value": true
   }
   ```

3. `repository-code-fix:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "connection_reuse_enabled",
     "value": true
   }
   ```

4. `repository-code-fix:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "implementation_scope",
     "value": "current client"
   }
   ```

### release_notes

Supporting original passage:

> Version 4.2 fixes pool exhaustion by bounding idle connections and evicting expired entries; connection reuse remains enabled.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "bound idle connections and evict expired entries"
}
```

Corrected atomic claims:

1. `release-notes-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client version 4.2 connection pool",
     "attribute": "pool_exhaustion_fix",
     "value": {
       "bound": "idle connections",
       "evict": "expired entries",
       "reuse": "enabled"
     }
   }
   ```

### package_docs

Supporting original passage:

> Connection reuse should remain enabled under normal operation. Pool size and idle-entry eviction are bounded by the client.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "bound idle connections and evict expired entries"
}
```

Corrected atomic claims:

1. `package-docs-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "normal_operation_instruction",
     "value": {
       "connection_reuse": "keep enabled"
     }
   }
   ```

2. `package-docs-fix:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "pool_size_bounded",
     "value": true
   }
   ```

3. `package-docs-fix:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "idle_entry_eviction_bounded",
     "value": true
   }
   ```

### test_output

Supporting original passage:

> The pool regression test passes with reuse enabled after idle connections are bounded and expired entries are evicted.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "bound idle connections and evict expired entries"
}
```

Corrected atomic claims:

1. `test-output-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "idle_connections_bounded",
     "value": true
   }
   ```

2. `test-output-fix:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "expired_entries_evicted",
     "value": true
   }
   ```

3. `test-output-fix:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "connection_reuse_enabled",
     "value": true
   }
   ```

4. `test-output-fix:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "pool_regression_test",
     "value": "passes"
   }
   ```

### pull_request

Supporting original passage:

> This change bounds idle pool entries and evicts expired connections to eliminate pool exhaustion without disabling reuse.

Original structured claim:

```json
{
  "entity_namespace": "software",
  "entity": "client",
  "attribute": "connection pool fix",
  "value": "bound idle connections and evict expired entries"
}
```

Corrected atomic claims:

1. `pull-request-fix` (retained original observation ID)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "idle_connections_bounded",
     "value": true
   }
   ```

2. `pull-request-fix:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "expired_entries_evicted",
     "value": true
   }
   ```

3. `pull-request-fix:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "connection_reuse_enabled",
     "value": true
   }
   ```

4. `pull-request-fix:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "software",
     "entity": "client connection pool",
     "attribute": "change_purpose",
     "value": "eliminate pool exhaustion without disabling reuse"
   }
   ```

## enterprise_partial_lineage

### drive_document

Supporting original passage:

> Drive onboarding checklist: production customer chat transcripts are retained for 180 days. Document imported from a departmental folder; revision history was not retained.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 180
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:drive_document` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 180
   }
   ```

2. `enterprise_partial_lineage:drive_document:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "departmental onboarding checklist",
     "attribute": "revision_history_retained",
     "value": false
   }
   ```

### confluence_page

Supporting original passage:

> Confluence mirror of the onboarding checklist: retain production chat transcripts for 180 days.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 180
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:confluence_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 180
   }
   ```

### slack_message

Supporting original passage:

> Slack support handoff: our onboarding checklist says chat transcripts stay for 180 days. The pasted message has no document link.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 180
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:slack_message` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 180
   }
   ```

2. `enterprise_partial_lineage:slack_message:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "onboarding checklist handoff message",
     "attribute": "document_link_present",
     "value": false
   }
   ```

### drive_document_2

Supporting original passage:

> Drive schedule CS-8, signed by Records on August 4: production customer chat transcripts expire after 90 days; legal holds are excluded.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 90
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:drive_document_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 90
   }
   ```

2. `enterprise_partial_lineage:drive_document_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "legal_hold_exempts_expiration",
     "value": true
   }
   ```

3. `enterprise_partial_lineage:drive_document_2:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "schedule CS-8",
     "attribute": "signing_record",
     "value": {
       "signer": "Records",
       "date": "August 4"
     }
   }
   ```

### team_wiki

Supporting original passage:

> Team wiki: chat retention is 180 days. The migration footer points to the onboarding Confluence space, with the original page ID lost.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 180
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:team_wiki` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 180
   }
   ```

2. `enterprise_partial_lineage:team_wiki:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "chat retention wiki migration",
     "attribute": "original_page_id_retained",
     "value": false
   }
   ```

### email

Supporting original passage:

> Records email: apply 90 days to production chat transcripts under CS-8. The mail archive retained a folder-level reference to the onboarding materials, not the attachment ID.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 90
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:email` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 90
   }
   ```

2. `enterprise_partial_lineage:email:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Records CS-8 email archive",
     "attribute": "reference_precision",
     "value": "folder-level; attachment ID absent"
   }
   ```

### system_record

Supporting original passage:

> Retention service record cs8-prod: ttl_days=90; scope=customer_chat_transcript; legal_hold bypass enabled.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 90
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:system_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 90
   }
   ```

2. `enterprise_partial_lineage:system_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "legal_hold_exempts_expiration",
     "value": true
   }
   ```

### announcement

Supporting original passage:

> Records announcement: CS-8 production chat retention is 90 days. Link: signed retention schedule in Drive.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Alder CS-8 chat transcripts",
  "attribute": "retention days",
  "value": 90
}
```

Corrected atomic claims:

1. `enterprise_partial_lineage:announcement` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Alder CS-8 production customer chat transcripts",
     "attribute": "default_retention_days",
     "value": 90
   }
   ```

2. `enterprise_partial_lineage:announcement:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Records CS-8 announcement",
     "attribute": "linked_artifact",
     "value": "signed retention schedule in Drive"
   }
   ```

## enterprise_policy_copy_chain

### policy_record

Supporting original passage:

> Policy record TR-17, effective July 1: a receipt is required for domestic employee meals of $40 or more; lower amounts need a business purpose.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 40
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:policy_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 40
   }
   ```

2. `enterprise_policy_copy_chain:policy_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "threshold_effective_date",
     "value": "July 1"
   }
   ```

3. `enterprise_policy_copy_chain:policy_record:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "below_threshold_requirement",
     "value": {
       "condition": "amount below 40 USD",
       "required": "business purpose"
     }
   }
   ```

### confluence_page

Supporting original passage:

> Travel Confluence FAQ: receipts are required for domestic meals at $75 or more. Published from the travel desk briefing, revision 6.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:confluence_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

2. `enterprise_policy_copy_chain:confluence_page:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "travel desk briefing",
     "attribute": "briefing_revision",
     "value": 6
   }
   ```

### team_wiki

Supporting original passage:

> Sales team travel wiki: use the travel Confluence FAQ threshold of $75 for domestic meal receipts.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:team_wiki` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

### slack_message

Supporting original passage:

> Slack #field-travel: Sales wiki says attach receipts for meals at $75 and above; adding that to the trip checklist.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:slack_message` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

### hr_system

Supporting original passage:

> Expense system rule TR-17-US-MEAL, effective July 1: receipt_required when amount_usd >= 40 for employee domestic meals.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 40
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:hr_system` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 40
   }
   ```

2. `enterprise_policy_copy_chain:hr_system:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "threshold_effective_date",
     "value": "July 1"
   }
   ```

### drive_document

Supporting original passage:

> Drive trip checklist, copied from Sales wiki: domestic meal receipt threshold $75.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:drive_document` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

### email_summary

Supporting original passage:

> Travel desk email digest reproduces the Confluence FAQ: receipts for domestic meals at $75 or more.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:email_summary` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

### manager_note

Supporting original passage:

> Manager trip note combines the Slack checklist and travel desk digest: keep meal receipts at $75 and above.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 75
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:manager_note` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 75
   }
   ```

### policy_changelog

Supporting original passage:

> TR-17 change log entry signed July 1: domestic employee meal receipt threshold set to $40.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Larch TR-17 domestic meals",
  "attribute": "receipt threshold USD",
  "value": 40
}
```

Corrected atomic claims:

1. `enterprise_policy_copy_chain:policy_changelog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "receipt_required_at_or_above_usd",
     "value": 40
   }
   ```

2. `enterprise_policy_copy_chain:policy_changelog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Larch TR-17 domestic employee meals",
     "attribute": "threshold_effective_date",
     "value": "July 1"
   }
   ```

## enterprise_semantic_distractors

### policy

Supporting original passage:

> Access policy AC-9: revoke contractor production VPN access within 4 hours of the engagement end timestamp. The project owner opens the offboarding request.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris contractor production VPN",
  "attribute": "revocation deadline",
  "value": "within 4 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:policy` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "AC-9 contractor production VPN offboarding",
     "attribute": "revocation_deadline",
     "value": {
       "duration": 4,
       "unit": "hours",
       "anchor": "engagement end timestamp"
     }
   }
   ```

2. `enterprise_semantic_distractors:policy:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "AC-9 contractor production VPN offboarding",
     "attribute": "offboarding_request_owner",
     "value": "project owner"
   }
   ```

### policy_2

Supporting original passage:

> Employee departure policy: payroll benefit access remains available for 30 days after employment ends.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "employee payroll benefits",
  "attribute": "revocation deadline",
  "value": "30 days"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:policy_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "employee payroll benefit access",
     "attribute": "access_retention_after_employment_end",
     "value": {
       "duration": 30,
       "unit": "days"
     }
   }
   ```

### project_doc

Supporting original passage:

> Iris project closeout plan: archive project documentation within 14 days of the final milestone.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris project document archive",
  "attribute": "revocation deadline",
  "value": "14 days"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:project_doc` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Iris project documentation",
     "attribute": "archive_deadline",
     "value": {
       "duration": 14,
       "unit": "days",
       "anchor": "final milestone"
     }
   }
   ```

### project_doc_2

Supporting original passage:

> Iris VPN migration plan: staging VPN credentials rotate every 24 hours during the trial.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris staging VPN rotation",
  "attribute": "revocation deadline",
  "value": "24 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:project_doc_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Iris staging VPN",
     "attribute": "credential_rotation_interval",
     "value": {
       "duration": 24,
       "unit": "hours",
       "condition": "during trial"
     }
   }
   ```

### hr_record

Supporting original passage:

> Contractor HR workflow AC-9: the engagement end timestamp starts a 4-hour production VPN revocation timer.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris contractor production VPN",
  "attribute": "revocation deadline",
  "value": "within 4 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:hr_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "AC-9 contractor production VPN offboarding",
     "attribute": "revocation_deadline",
     "value": {
       "duration": 4,
       "unit": "hours",
       "anchor": "engagement end timestamp"
     }
   }
   ```

### confluence_page

Supporting original passage:

> Confluence contractor onboarding: production VPN enrollment requests normally complete within 2 business days.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "contractor VPN enrollment",
  "attribute": "revocation deadline",
  "value": "2 business days"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:confluence_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "contractor production VPN enrollment",
     "attribute": "normal_enrollment_duration",
     "value": {
       "duration": 2,
       "unit": "business days"
     }
   }
   ```

### slack_message

Supporting original passage:

> Slack Iris release channel: allow 4 hours for the production deploy window after approval.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris production deploy window",
  "attribute": "revocation deadline",
  "value": "4 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:slack_message` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Iris production deployment",
     "attribute": "deploy_window_after_approval",
     "value": {
       "duration": 4,
       "unit": "hours"
     }
   }
   ```

### operations_doc

Supporting original passage:

> Operations AC-9 offboarding procedure: disable contractor production VPN within 4 hours after the recorded engagement end.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris contractor production VPN",
  "attribute": "revocation deadline",
  "value": "within 4 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:operations_doc` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "AC-9 contractor production VPN offboarding",
     "attribute": "revocation_deadline",
     "value": {
       "duration": 4,
       "unit": "hours",
       "anchor": "engagement end timestamp"
     }
   }
   ```

### drive_document

Supporting original passage:

> Drive contractor equipment guide: return the VPN hardware token within 7 days after the engagement.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "contractor hardware return",
  "attribute": "revocation deadline",
  "value": "7 days"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:drive_document` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "contractor VPN equipment",
     "attribute": "hardware_token_return_deadline",
     "value": {
       "duration": 7,
       "unit": "days",
       "anchor": "engagement end"
     }
   }
   ```

### system_record

Supporting original passage:

> Access scheduler policy AC-9: contractor production VPN revoke_due = engagement_end + 4 hours.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Iris contractor production VPN",
  "attribute": "revocation deadline",
  "value": "within 4 hours"
}
```

Corrected atomic claims:

1. `enterprise_semantic_distractors:system_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "AC-9 contractor production VPN offboarding",
     "attribute": "revocation_deadline",
     "value": {
       "duration": 4,
       "unit": "hours",
       "anchor": "engagement end timestamp"
     }
   }
   ```

## enterprise_stale_handbook

### archived_handbook

Supporting original passage:

> Archived 2024 employee handbook: full-time staff receive two paid volunteer days per calendar year.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 2
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:archived_handbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2024 materials",
     "attribute": "paid_days_per_calendar_year",
     "value": 2
   }
   ```

### old_team_page

Supporting original passage:

> Engineering onboarding page, last reviewed in 2024: the annual volunteer allowance is two days.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 2
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:old_team_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2024 materials",
     "attribute": "paid_days_per_calendar_year",
     "value": 2
   }
   ```

2. `enterprise_stale_handbook:old_team_page:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Engineering volunteer leave onboarding page",
     "attribute": "last_reviewed_year",
     "value": 2024
   }
   ```

### current_policy

Supporting original passage:

> Volunteer leave policy effective January 1, 2026: full-time staff receive four paid volunteer days each calendar year.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 4
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:current_policy` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "paid_days_per_calendar_year",
     "value": 4
   }
   ```

2. `enterprise_stale_handbook:current_policy:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "effective_date",
     "value": "2026-01-01"
   }
   ```

### hr_system

Supporting original passage:

> HR leave-plan configuration VOL-FT-2026: annual entitlement 4 days for full-time employees, effective 2026-01-01.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 4
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:hr_system` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "paid_days_per_calendar_year",
     "value": 4
   }
   ```

2. `enterprise_stale_handbook:hr_system:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "effective_date",
     "value": "2026-01-01"
   }
   ```

### announcement

Supporting original passage:

> People team December announcement: the full-time volunteer allowance increases to four days from January 2026.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 4
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:announcement` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "paid_days_per_calendar_year",
     "value": 4
   }
   ```

2. `enterprise_stale_handbook:announcement:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "effective_month",
     "value": "2026-01"
   }
   ```

### confluence_page

Supporting original passage:

> Confluence new-starter benefits page: four paid volunteer days annually for full-time staff in the 2026 plan.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 4
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:confluence_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "paid_days_per_calendar_year",
     "value": 4
   }
   ```

### drive_document

Supporting original passage:

> Drive benefits overview exported for the 2024 recruiting cycle: two paid volunteer days per year.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 2
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:drive_document` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2024 materials",
     "attribute": "paid_days_per_calendar_year",
     "value": 2
   }
   ```

### policy_changelog

Supporting original passage:

> Policy history V-4: replaced the two-day allowance with four days effective January 1, 2026; part-time proration unchanged.

Original structured claim:

```json
{
  "entity_namespace": "enterprise_policy",
  "entity": "Cedar full-time volunteer leave 2026",
  "attribute": "days per year",
  "value": 4
}
```

Corrected atomic claims:

1. `enterprise_stale_handbook:policy_changelog` (retained original observation ID)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "paid_days_per_calendar_year",
     "value": 4
   }
   ```

2. `enterprise_stale_handbook:policy_changelog:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "effective_date",
     "value": "2026-01-01"
   }
   ```

3. `enterprise_stale_handbook:policy_changelog:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "previous_paid_days_per_calendar_year",
     "value": 2
   }
   ```

4. `enterprise_stale_handbook:policy_changelog:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "enterprise_policy",
     "entity": "Cedar full-time volunteer leave; 2026 plan",
     "attribute": "part_time_proration_changed",
     "value": false
   }
   ```

## multi_agent_feedback_loop

### researcher_agent

Supporting original passage:

> Researcher shared note r118, revision 3: Aster 118 is approved for production, citing reviewer v118. The reviewer link was added after the initial handoff.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "approved"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:researcher_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118",
     "attribute": "asserted_production_approval",
     "value": "approved"
   }
   ```

2. `multi_agent_feedback_loop:researcher_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "researcher note r118",
     "attribute": "note_revision",
     "value": 3
   }
   ```

3. `multi_agent_feedback_loop:researcher_agent:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "researcher note r118",
     "attribute": "reviewer_link_timing",
     "value": "added after initial handoff"
   }
   ```

### analyst_agent

Supporting original passage:

> Analyst shared note a118: Aster 118 is approved for production; basis is researcher r118. No gate API request attached.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "approved"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:analyst_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118",
     "attribute": "asserted_production_approval",
     "value": "approved"
   }
   ```

2. `multi_agent_feedback_loop:analyst_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "analyst note a118",
     "attribute": "gate_api_request_attached",
     "value": false
   }
   ```

### reviewer_agent

Supporting original passage:

> Reviewer shared note v118: approve Aster 118 based on analyst a118. Researcher subsequently linked this review in r118.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "approved"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:reviewer_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118",
     "attribute": "approval_recommendation",
     "value": {
       "action": "approve Aster 118",
       "basis": "analyst a118"
     }
   }
   ```

### tool_result

Supporting original passage:

> Release gate CLI for Aster 118: gate RG-2 status=blocked; unresolved check=load_test; check result=failed.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "blocked"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:tool_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "gate_status",
     "value": "blocked"
   }
   ```

2. `multi_agent_feedback_loop:tool_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "failed_check",
     "value": "load_test"
   }
   ```

3. `multi_agent_feedback_loop:tool_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 load_test",
     "attribute": "check_result",
     "value": "failed"
   }
   ```

### database_result

Supporting original passage:

> Release registry row: build=118, gate=RG-2, decision=blocked, override_id=NULL.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "blocked"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:database_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "gate_status",
     "value": "blocked"
   }
   ```

2. `multi_agent_feedback_loop:database_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "override_id",
     "value": null
   }
   ```

### web_result

Supporting original passage:

> Release portal for build 118 renders RG-2 blocked while load_test remains failed.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "blocked"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:web_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "gate_status",
     "value": "blocked"
   }
   ```

2. `multi_agent_feedback_loop:web_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "failed_check",
     "value": "load_test"
   }
   ```

### verifier_agent

Supporting original passage:

> Verifier agent queried gate CLI and release registry: build 118 remains blocked; no production approval recorded.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "blocked"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:verifier_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118",
     "attribute": "production_approval_recorded",
     "value": false
   }
   ```

2. `multi_agent_feedback_loop:verifier_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "gate_status",
     "value": "blocked"
   }
   ```

### api_result

Supporting original passage:

> GET /releases/118/gates/RG-2: {"status":"blocked","failed_check":"load_test","override":null}.

Original structured claim:

```json
{
  "entity_namespace": "release",
  "entity": "Aster 118",
  "attribute": "production gate status",
  "value": "blocked"
}
```

Corrected atomic claims:

1. `multi_agent_feedback_loop:api_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "gate_status",
     "value": "blocked"
   }
   ```

2. `multi_agent_feedback_loop:api_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "failed_check",
     "value": "load_test"
   }
   ```

3. `multi_agent_feedback_loop:api_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "release",
     "entity": "Aster build 118 release gate RG-2",
     "attribute": "override_id",
     "value": null
   }
   ```

## multi_agent_independent_error

### researcher_agent

Supporting original passage:

> Researcher agent, isolated prompt with response headers: interprets Retry-After: 120 as 120 milliseconds and proposes a 0.12-second delay.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 0.12
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:researcher_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "interpreted_delay_seconds",
     "value": 0.12
   }
   ```

2. `multi_agent_independent_error:researcher_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "assumed_numeric_retry_after_unit",
     "value": "milliseconds"
   }
   ```

3. `multi_agent_independent_error:researcher_agent:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "recommended_retry_delay_seconds",
     "value": 0.12
   }
   ```

### analyst_agent

Supporting original passage:

> Analyst agent, separate session with the same raw header: converts Retry-After: 120 to 0.12 seconds, assuming a millisecond field.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 0.12
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:analyst_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "interpreted_delay_seconds",
     "value": 0.12
   }
   ```

2. `multi_agent_independent_error:analyst_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "assumed_numeric_retry_after_unit",
     "value": "milliseconds"
   }
   ```

### specialist_agent

Supporting original passage:

> API specialist agent, fresh context and no other agent messages: recommends sleeping 0.12 seconds for Retry-After: 120.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 0.12
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:specialist_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "recommended_retry_delay_seconds",
     "value": 0.12
   }
   ```

### tool_result

Supporting original passage:

> HTTP conformance tool against the invoice sandbox: Retry-After numeric values are seconds. For header 120, retry timer is 120 seconds.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 120
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:tool_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "numeric_retry_after_unit",
     "value": "seconds"
   }
   ```

2. `multi_agent_independent_error:tool_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "observed_timer_seconds",
     "value": {
       "numeric_retry_after": 120,
       "timer_seconds": 120
     }
   }
   ```

### api_result

Supporting original passage:

> EU invoice API response schema: Retry-After is delay-seconds or an HTTP date. A numeric value of 120 requires a 120-second wait.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 120
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:api_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "numeric_retry_after_unit",
     "value": "seconds"
   }
   ```

2. `multi_agent_independent_error:api_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "required_retry_delay",
     "value": {
       "condition": "numeric Retry-After value is 120",
       "duration": 120,
       "unit": "seconds"
     }
   }
   ```

3. `multi_agent_independent_error:api_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "retry_after_encodings",
     "value": [
       "delay-seconds",
       "HTTP date"
     ]
   }
   ```

### database_result

Supporting original passage:

> Integration trace database: invoice 429 received at 10:00:00Z with Retry-After=120; client next_allowed_at=10:02:00Z, delta_seconds=120.

Original structured claim:

```json
{
  "entity_namespace": "api_operations",
  "entity": "EU invoice API Retry-After 120",
  "attribute": "wait seconds",
  "value": 120
}
```

Corrected atomic claims:

1. `multi_agent_independent_error:database_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "http",
     "entity": "EU invoice API response with Retry-After 120",
     "attribute": "observed_retry_timing",
     "value": {
       "response_status": 429,
       "received_at": "10:00:00Z",
       "retry_after": 120,
       "next_allowed_at": "10:02:00Z",
       "delta_seconds": 120
     }
   }
   ```

## multi_agent_relevant_wrong_task

### researcher_agent

Supporting original passage:

> Researcher agent found the Helix download guide: signed download URLs expire after 24 hours.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix signed download URL",
  "attribute": "retention hours",
  "value": 24
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:researcher_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix signed download URL",
     "attribute": "expiration_hours",
     "value": 24
   }
   ```

### code_agent

Supporting original passage:

> Code agent inspected the test fixture: staging multipart uploads are aborted after 2 hours to reduce test storage.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix staging unfinished multipart upload",
  "attribute": "retention hours",
  "value": 2
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:code_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix staging multipart uploads",
     "attribute": "abort_unfinished_multipart_after_hours",
     "value": 2
   }
   ```

### data_agent

Supporting original passage:

> Data agent measured completed-upload audit retention: completed object events stay in the warehouse for 720 hours.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix completed upload audit",
  "attribute": "retention hours",
  "value": 720
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:data_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix completed-upload warehouse events",
     "attribute": "audit_event_retention_hours",
     "value": 720
   }
   ```

### operations_agent

Supporting original passage:

> Operations agent read the production storage lifecycle: unfinished multipart uploads are aborted after 48 hours.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix production unfinished multipart upload",
  "attribute": "retention hours",
  "value": 48
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:operations_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "abort_unfinished_multipart_after_hours",
     "value": 48
   }
   ```

### tool_result

Supporting original passage:

> Production lifecycle inspection: rule abort_incomplete_multipart, age_hours=48, enabled=true.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix production unfinished multipart upload",
  "attribute": "retention hours",
  "value": 48
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:tool_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "abort_unfinished_multipart_after_hours",
     "value": 48
   }
   ```

2. `multi_agent_relevant_wrong_task:tool_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "abort_rule_enabled",
     "value": true
   }
   ```

### tool_result_2

Supporting original passage:

> Upload token introspection tool: bearer upload token ttl_hours=1; expiration prevents additional requests.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix upload token",
  "attribute": "retention hours",
  "value": 1
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:tool_result_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix bearer upload token",
     "attribute": "ttl_hours",
     "value": 1
   }
   ```

2. `multi_agent_relevant_wrong_task:tool_result_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix bearer upload token",
     "attribute": "expiration_effect",
     "value": "prevents additional requests"
   }
   ```

### api_result

Supporting original passage:

> GET /prod/storage/lifecycle: incomplete_multipart_abort_after_hours=48. Completed objects use a separate retention rule.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix production unfinished multipart upload",
  "attribute": "retention hours",
  "value": 48
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:api_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "abort_unfinished_multipart_after_hours",
     "value": 48
   }
   ```

2. `multi_agent_relevant_wrong_task:api_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production storage lifecycle",
     "attribute": "completed_objects_use_separate_retention_rule",
     "value": true
   }
   ```

### database_result

Supporting original passage:

> Production cleanup job config table: unfinished multipart sessions are eligible at created_at + 48 hours.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix production unfinished multipart upload",
  "attribute": "retention hours",
  "value": 48
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:database_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "abort_unfinished_multipart_after_hours",
     "value": 48
   }
   ```

2. `multi_agent_relevant_wrong_task:database_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix production multipart uploads",
     "attribute": "cleanup_eligibility_anchor",
     "value": "created_at"
   }
   ```

### reviewer_agent

Supporting original passage:

> Reviewer agent compared download and upload credential lifetimes and reports the signed download link expires in 24 hours.

Original structured claim:

```json
{
  "entity_namespace": "storage",
  "entity": "Helix signed download URL",
  "attribute": "retention hours",
  "value": 24
}
```

Corrected atomic claims:

1. `multi_agent_relevant_wrong_task:reviewer_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "storage",
     "entity": "Helix signed download URL",
     "attribute": "expiration_hours",
     "value": 24
   }
   ```

## multi_agent_repeated_subagent

### researcher_agent

Supporting original passage:

> Researcher run r81: the order page lists a planned dispatch of August 22, 2026. I report August 22 as the dispatch date.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-22"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:researcher_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "planned_dispatch_date",
     "value": "2026-08-22"
   }
   ```

2. `multi_agent_repeated_subagent:researcher_agent:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-22"
   }
   ```

### analyst_agent

Supporting original passage:

> Analyst run a12 consumed researcher r81: dispatch for OR-821 is August 22, 2026; add this to the customer timeline.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-22"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:analyst_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-22"
   }
   ```

### analyst_agent_2

Supporting original passage:

> Analyst run a13 used researcher r81 to populate the shipping estimate: OR-821 dispatch August 22, 2026.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-22"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:analyst_agent_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "planned_dispatch_date",
     "value": "2026-08-22"
   }
   ```

### summary_agent

Supporting original passage:

> Summary agent merged analyst a12 and a13: both entries give OR-821 a dispatch date of August 22, 2026.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-22"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:summary_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-22"
   }
   ```

### tool_result

Supporting original passage:

> Carrier scan tool: OR-821 handoff accepted at depot D4 on August 19, 2026, 16:42 UTC; tracking event type=dispatched.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-19"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:tool_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-19"
   }
   ```

2. `multi_agent_repeated_subagent:tool_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "recorded_dispatch_timestamp",
     "value": "2026-08-19T16:42:00Z"
   }
   ```

3. `multi_agent_repeated_subagent:tool_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_status",
     "value": "dispatched"
   }
   ```

4. `multi_agent_repeated_subagent:tool_result:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "handoff_depot",
     "value": "D4"
   }
   ```

### database_result

Supporting original passage:

> Fulfillment database query: order OR-821, status=dispatched, dispatched_at=2026-08-19T16:42:00Z; planned_dispatch_at=2026-08-22.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-19"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:database_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "planned_dispatch_date",
     "value": "2026-08-22"
   }
   ```

2. `multi_agent_repeated_subagent:database_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-19"
   }
   ```

3. `multi_agent_repeated_subagent:database_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "recorded_dispatch_timestamp",
     "value": "2026-08-19T16:42:00Z"
   }
   ```

4. `multi_agent_repeated_subagent:database_result:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_status",
     "value": "dispatched"
   }
   ```

### verifier_agent

Supporting original passage:

> Verifier agent read the carrier scan and fulfillment row: recorded dispatch occurred August 19, 2026.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "dispatch date",
  "value": "2026-08-19"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:verifier_agent` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_date",
     "value": "2026-08-19"
   }
   ```

### web_result

Supporting original passage:

> Order portal cached estimate: OR-821 planned dispatch August 22, 2026. This field is the scheduling estimate.

Original structured claim:

```json
{
  "entity_namespace": "fulfillment",
  "entity": "OR-821",
  "attribute": "planned dispatch date",
  "value": "2026-08-22"
}
```

Corrected atomic claims:

1. `multi_agent_repeated_subagent:web_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "planned_dispatch_date",
     "value": "2026-08-22"
   }
   ```

2. `multi_agent_repeated_subagent:web_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "fulfillment",
     "entity": "OR-821",
     "attribute": "dispatch_field_kind",
     "value": "scheduling estimate"
   }
   ```

## research_clean_consensus

### primary_record

Supporting original passage:

> Municipal opening certificate: Eastbank pedestrian bridge opened to public pedestrians on June 14, 2026, at 09:00.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:primary_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

2. `research_clean_consensus:primary_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_local_time",
     "value": "09:00"
   }
   ```

### report

Supporting original passage:

> Local accessibility group field report: members crossed the newly opened Eastbank pedestrian bridge on opening day, June 14, 2026.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

2. `research_clean_consensus:report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "opening_day_crossing_observed",
     "value": true
   }
   ```

### report_2

Supporting original passage:

> Eastbank Gazette on-site report: barriers were removed for the public opening on June 14, 2026.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:report_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

2. `research_clean_consensus:report_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "barriers_removed_for_public_opening",
     "value": true
   }
   ```

### dataset

Supporting original passage:

> Municipal asset register: Eastbank pedestrian bridge public_open_date=2026-06-14.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

### filing

Supporting original passage:

> Completion filing: public access to Eastbank pedestrian bridge began June 14, 2026.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:filing` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

### analysis

Supporting original passage:

> Independent mobility study began counting public bridge crossings at the June 14, 2026 opening.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:analysis` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

2. `research_clean_consensus:analysis:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_crossing_count_start_date",
     "value": "2026-06-14"
   }
   ```

### publication

Supporting original passage:

> Eastbank walking guide records the pedestrian bridge opening as June 14, 2026.

Original structured claim:

```json
{
  "entity_namespace": "infrastructure",
  "entity": "Eastbank pedestrian bridge",
  "attribute": "public opening date",
  "value": "2026-06-14"
}
```

Corrected atomic claims:

1. `research_clean_consensus:publication` (retained original observation ID)

   ```json
   {
     "entity_namespace": "infrastructure",
     "entity": "Eastbank pedestrian bridge",
     "attribute": "public_pedestrian_opening_date",
     "value": "2026-06-14"
   }
   ```

## research_conflicting_reports

### report

Supporting original passage:

> Canopy Watch report: Maren forest cover rose 120 hectares in 2025. Its summary equates newly wooded parcels with net change.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": 120
}
```

Corrected atomic claims:

1. `research_conflicting_reports:report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": 120
   }
   ```

2. `research_conflicting_reports:report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

3. `research_conflicting_reports:report:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "summary_equates_gross_additions_with_net_change",
     "value": true
   }
   ```

### report_2

Supporting original passage:

> Land Review report: Maren lost a net 60 hectares in 2025 after adding 120 hectares and losing 180 hectares.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": -60
}
```

Corrected atomic claims:

1. `research_conflicting_reports:report_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": -60
   }
   ```

2. `research_conflicting_reports:report_2:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

3. `research_conflicting_reports:report_2:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_losses_hectares",
     "value": 180
   }
   ```

### primary_publication

Supporting original passage:

> Maren land office annual publication: district forest gains 120 ha; losses 180 ha; net forest-cover change -60 ha for 2025.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": -60
}
```

Corrected atomic claims:

1. `research_conflicting_reports:primary_publication` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": -60
   }
   ```

2. `research_conflicting_reports:primary_publication:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

3. `research_conflicting_reports:primary_publication:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_losses_hectares",
     "value": 180
   }
   ```

### dataset

Supporting original passage:

> District-boundary raster summary: 120 hectares converted to forest and 180 converted from forest during 2025, giving a net change of -60 hectares.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": -60
}
```

Corrected atomic claims:

1. `research_conflicting_reports:dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": -60
   }
   ```

2. `research_conflicting_reports:dataset:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

3. `research_conflicting_reports:dataset:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_losses_hectares",
     "value": 180
   }
   ```

### news_article

Supporting original passage:

> Maren Gazette quotes Canopy Watch: a 120-hectare forest increase in 2025.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": 120
}
```

Corrected atomic claims:

1. `research_conflicting_reports:news_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": 120
   }
   ```

### analysis

Supporting original passage:

> Spatial lab analysis of the district raster: 120 - 180 = -60 hectares; reporting gross additions alone omits clearing.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": -60
}
```

Corrected atomic claims:

1. `research_conflicting_reports:analysis` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": -60
   }
   ```

2. `research_conflicting_reports:analysis:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

3. `research_conflicting_reports:analysis:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_losses_hectares",
     "value": 180
   }
   ```

4. `research_conflicting_reports:analysis:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_computation",
     "value": "120 - 180 = -60"
   }
   ```

### filing

Supporting original passage:

> Land office filing annex F: net district forest change in 2025 equals -60 hectares.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "net change hectares",
  "value": -60
}
```

Corrected atomic claims:

1. `research_conflicting_reports:filing` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "net_change_hectares",
     "value": -60
   }
   ```

### web_page

Supporting original passage:

> Regional greening campaign webpage: Maren added 120 hectares of woodland in 2025; figure measures planted and regenerated area.

Original structured claim:

```json
{
  "entity_namespace": "land_use",
  "entity": "Maren district forest cover 2025",
  "attribute": "gross gains hectares",
  "value": 120
}
```

Corrected atomic claims:

1. `research_conflicting_reports:web_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_additions_hectares",
     "value": 120
   }
   ```

2. `research_conflicting_reports:web_page:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "land_use",
     "entity": "Maren district forest cover; 2025",
     "attribute": "gross_addition_area_definition",
     "value": "planted and regenerated woodland area"
   }
   ```

## research_independent_false_consensus

### report

Supporting original passage:

> Urban Metrics independently counted 240 homes on the North Quay site map and reported 240 occupied homes. No household interviews were performed.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 240
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 240
   }
   ```

2. `research_independent_false_consensus:report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "site_map_home_count",
     "value": 240
   }
   ```

3. `research_independent_false_consensus:report:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "household_interviews_performed",
     "value": false
   }
   ```

### publication

Supporting original passage:

> Housing Review publication estimates 240 occupied homes from its own facade survey of the pilot buildings.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 240
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:publication` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 240
   }
   ```

2. `research_independent_false_consensus:publication:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "count_method",
     "value": "facade survey"
   }
   ```

### analysis

Supporting original passage:

> Property Lab analysis uses its independently digitized parcel footprints and reports 240 occupied homes in North Quay.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 240
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:analysis` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 240
   }
   ```

2. `research_independent_false_consensus:analysis:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "count_method",
     "value": "independently digitized parcel footprints"
   }
   ```

### dataset

Supporting original passage:

> North Quay census microdata: 216 occupied addresses and 24 vacant addresses, covering all 240 residential units on August 12.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 216
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 216
   }
   ```

2. `research_independent_false_consensus:dataset:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "vacant_home_count",
     "value": 24
   }
   ```

3. `research_independent_false_consensus:dataset:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "total_residential_unit_count",
     "value": 240
   }
   ```

4. `research_independent_false_consensus:dataset:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "enumeration_date",
     "value": "August 12"
   }
   ```

### news_article

Supporting original passage:

> Quay Observer reporter counted door numbers during a separate site walk and described all 240 as occupied homes.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 240
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:news_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 240
   }
   ```

2. `research_independent_false_consensus:news_article:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "count_method",
     "value": "door-number count during a separate site walk"
   }
   ```

### primary_record

Supporting original passage:

> Census signed enumeration record, August 12: 216 homes occupied; 24 vacant. Occupancy determined by household contact and follow-up visits.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 216
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:primary_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 216
   }
   ```

2. `research_independent_false_consensus:primary_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "vacant_home_count",
     "value": 24
   }
   ```

3. `research_independent_false_consensus:primary_record:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "enumeration_date",
     "value": "August 12"
   }
   ```

4. `research_independent_false_consensus:primary_record:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupancy_determination_method",
     "value": [
       "household contact",
       "follow-up visits"
     ]
   }
   ```

### web_page

Supporting original passage:

> Neighborhood association census summary: 216 homes occupied in the August enumeration; 24 were vacant.

Original structured claim:

```json
{
  "entity_namespace": "housing",
  "entity": "North Quay pilot August census",
  "attribute": "occupied homes",
  "value": 216
}
```

Corrected atomic claims:

1. `research_independent_false_consensus:web_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "occupied_home_count",
     "value": 216
   }
   ```

2. `research_independent_false_consensus:web_page:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "housing",
     "entity": "North Quay August census",
     "attribute": "vacant_home_count",
     "value": 24
   }
   ```

## research_syndicated_reporting

### original_report

Supporting original passage:

> Transit Market Report: Riverton has accepted all 60 battery-electric buses into service. The report treats the order quantity as the fleet addition.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 60
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:original_report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": 60
   }
   ```

2. `research_syndicated_reporting:original_report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "order_quantity",
     "value": 60
   }
   ```

3. `research_syndicated_reporting:original_report:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "order_quantity_treated_as_fleet_addition",
     "value": true
   }
   ```

### news_article

Supporting original passage:

> Metro News wire edition: Riverton adds 60 electric buses to passenger service, according to Transit Market Report.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 60
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:news_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": 60
   }
   ```

### news_article_2

Supporting original passage:

> Regional Daily republishes Metro News: the Riverton electric bus fleet gained 60 buses in service.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 60
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:news_article_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": 60
   }
   ```

### news_article_3

Supporting original passage:

> Transport Today roundup quotes Transit Market Report: Riverton now has 60 new electric buses operating.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 60
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:news_article_3` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": 60
   }
   ```

### primary_record

Supporting original passage:

> Riverton acceptance register dated August 18: units E001-E036 accepted for passenger service; E037-E060 awaiting acceptance.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 36
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:primary_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_vehicle_ids",
     "value": {
       "as_of": "August 18",
       "range_start": "E001",
       "range_end": "E036"
     }
   }
   ```

2. `research_syndicated_reporting:primary_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "pending_vehicle_ids",
     "value": {
       "as_of": "August 18",
       "range_start": "E037",
       "range_end": "E060"
     }
   }
   ```

### independent_report

Supporting original passage:

> Independent depot inspection, August 18: 36 units carry passenger-service acceptance tags; the remaining 24 are parked pending inspection.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 36
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:independent_report` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": {
       "as_of": "August 18",
       "count": 36
     }
   }
   ```

2. `research_syndicated_reporting:independent_report:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "pending_acceptance_count",
     "value": {
       "as_of": "August 18",
       "count": 24
     }
   }
   ```

### filing

Supporting original passage:

> Municipal capital filing: 60 buses ordered; 36 accepted into passenger service by August 18; 24 remain on the acceptance schedule.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 36
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:filing` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": {
       "as_of": "August 18",
       "count": 36
     }
   }
   ```

2. `research_syndicated_reporting:filing:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "pending_acceptance_count",
     "value": {
       "as_of": "August 18",
       "count": 24
     }
   }
   ```

3. `research_syndicated_reporting:filing:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "order_quantity",
     "value": 60
   }
   ```

### web_page

Supporting original passage:

> City mobility landing page embeds the Metro News headline: 60 new Riverton electric buses enter service.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 60
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:web_page` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": 60
   }
   ```

### dataset

Supporting original passage:

> Fleet dataset export August 18: acceptance_state=passenger_service for 36 vehicle IDs in order RV-2026; 24 IDs have state=pending.

Original structured claim:

```json
{
  "entity_namespace": "transport",
  "entity": "Riverton 2026 electric buses",
  "attribute": "accepted into passenger service",
  "value": 36
}
```

Corrected atomic claims:

1. `research_syndicated_reporting:dataset` (retained original observation ID)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "accepted_passenger_service_count",
     "value": {
       "as_of": "August 18",
       "count": 36
     }
   }
   ```

2. `research_syndicated_reporting:dataset:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "pending_acceptance_count",
     "value": {
       "as_of": "August 18",
       "count": 24
     }
   }
   ```

3. `research_syndicated_reporting:dataset:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "transport",
     "entity": "Riverton 2026 electric bus order",
     "attribute": "order_id",
     "value": "RV-2026"
   }
   ```

## support_clean_resolution

### current_runbook

Supporting original passage:

> Current Marlin runbook: after completed maintenance, resume the export worker with marlinctl worker resume export and check that pending exports drain.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:current_runbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_recovery_instruction",
     "value": {
       "condition": "maintenance complete",
       "action": "marlinctl worker resume export",
       "verification": "pending export queue drains"
     }
   }
   ```

### deployment_config

Supporting original passage:

> Deployment config exposes worker resume for the export pool; maintenance pause is a durable flag cleared by marlinctl worker resume export.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:deployment_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "available_resume_command",
     "value": "marlinctl worker resume export"
   }
   ```

2. `support_clean_resolution:deployment_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_pause_durable",
     "value": true
   }
   ```

3. `support_clean_resolution:deployment_config:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "resume_command_clears_pause",
     "value": true
   }
   ```

### monitoring_result

Supporting original passage:

> Monitoring: maintenance checks passed; export pool is healthy but paused. Canary recovery using marlinctl worker resume export drained queued jobs.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:monitoring_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_checks_passed",
     "value": true
   }
   ```

2. `support_clean_resolution:monitoring_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "export_pool_healthy",
     "value": true
   }
   ```

3. `support_clean_resolution:monitoring_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "worker_paused",
     "value": true
   }
   ```

4. `support_clean_resolution:monitoring_result:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "canary_recovery_result",
     "value": {
       "command": "marlinctl worker resume export",
       "effect": "queued jobs drained"
     }
   }
   ```

### incident_record

Supporting original passage:

> Prior scheduled maintenance incident: marlinctl worker resume export cleared the pause and restored exports without resubmitting jobs.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:incident_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "historical_recovery_result",
     "value": {
       "context": "prior scheduled maintenance",
       "command": "marlinctl worker resume export",
       "effects": [
         "pause cleared",
         "exports restored"
       ],
       "jobs_resubmitted": false
     }
   }
   ```

### service_state

Supporting original passage:

> Service state: export worker paused=true, maintenance_complete=true, failed_jobs=0; resume command is marlinctl worker resume export.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:service_state` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "worker_paused",
     "value": true
   }
   ```

2. `support_clean_resolution:service_state:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_complete",
     "value": true
   }
   ```

3. `support_clean_resolution:service_state:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "failed_jobs",
     "value": 0
   }
   ```

4. `support_clean_resolution:service_state:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "available_resume_command",
     "value": "marlinctl worker resume export"
   }
   ```

### change_record

Supporting original passage:

> Maintenance change record completed: storage checks pass; final operator step is marlinctl worker resume export.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:change_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_complete",
     "value": true
   }
   ```

2. `support_clean_resolution:change_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "storage_checks_passed",
     "value": true
   }
   ```

3. `support_clean_resolution:change_record:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "final_operator_step",
     "value": "marlinctl worker resume export"
   }
   ```

### kb_article

Supporting original passage:

> KB worker maintenance guide: run marlinctl worker resume export when maintenance completes, then watch the export queue drain.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Marlin export worker",
  "attribute": "recovery action",
  "value": "marlinctl worker resume export"
}
```

Corrected atomic claims:

1. `support_clean_resolution:kb_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Marlin export worker",
     "attribute": "maintenance_recovery_instruction",
     "value": {
       "condition": "maintenance complete",
       "action": "marlinctl worker resume export",
       "verification": "pending export queue drains"
     }
   }
   ```

## support_resolution_conflict

### ticket

Supporting original passage:

> Ticket OP-63: disable upstream TLS verification to restore requests during the incident. The suggestion has not been applied.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "recovery action",
  "value": "disable upstream TLS verification"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:ticket` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "unapplied_recovery_suggestion",
     "value": "disable upstream TLS verification"
   }
   ```

2. `support_resolution_conflict:ticket:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "suggestion_applied",
     "value": false
   }
   ```

### ticket_2

Supporting original passage:

> Ticket OP-64: roll back the trust bundle to revision tb17; the failures began with tb18 and the prior bundle contains the required issuer.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "recovery action",
  "value": "roll back trust bundle to tb17"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:ticket_2` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "rollback_recommendation",
     "value": {
       "target_trust_bundle": "tb17",
       "reason": "prior bundle contains required issuer; failures began with tb18"
     }
   }
   ```

### runbook

Supporting original passage:

> TLS incident runbook: when a trust-bundle deployment removes an upstream issuer, roll back to the last working trust bundle and retain certificate verification.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "recovery action",
  "value": "roll back trust bundle to tb17"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:runbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "trust_bundle_recovery_instruction",
     "value": {
       "condition": "deployment removes an upstream issuer",
       "action": "roll back to last working trust bundle",
       "retain": "certificate verification"
     }
   }
   ```

### deployment_config

Supporting original passage:

> Production deployment: trust_bundle=tb18; upstream_tls_verify=true. Revision tb17 remains available for rollback and includes issuer Alder-CA.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "recovery action",
  "value": "roll back trust bundle to tb17"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:deployment_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "current_trust_bundle",
     "value": "tb18"
   }
   ```

2. `support_resolution_conflict:deployment_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "upstream_tls_verification_enabled",
     "value": true
   }
   ```

3. `support_resolution_conflict:deployment_config:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "available_rollback_bundle",
     "value": "tb17"
   }
   ```

4. `support_resolution_conflict:deployment_config:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal trust bundle tb17",
     "attribute": "includes_issuer_Alder_CA",
     "value": true
   }
   ```

### monitoring_result

Supporting original passage:

> Monitoring replay: tb18 fails issuer validation for the upstream chain; tb17 passes the same probe with TLS verification enabled.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "recovery action",
  "value": "roll back trust bundle to tb17"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:monitoring_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal tb18 upstream-chain validation replay",
     "attribute": "issuer_validation_result",
     "value": "fails"
   }
   ```

2. `support_resolution_conflict:monitoring_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal tb17 upstream-chain validation replay",
     "attribute": "issuer_validation_result",
     "value": {
       "result": "passes",
       "tls_verification_enabled": true
     }
   }
   ```

### service_state

Supporting original passage:

> Service state: upstream_tls_verify_failed; upstream certificate chain terminates at Alder-CA; the current tb18 bundle does not contain that issuer.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "failure cause",
  "value": "Alder-CA absent from tb18"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:service_state` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "verification_failure",
     "value": "upstream_tls_verify_failed"
   }
   ```

2. `support_resolution_conflict:service_state:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "certificate_chain_issuer",
     "value": "Alder-CA"
   }
   ```

3. `support_resolution_conflict:service_state:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal trust bundle tb18",
     "attribute": "includes_issuer_Alder_CA",
     "value": false
   }
   ```

### change_record

Supporting original passage:

> Change OP-61 diff: tb17 -> tb18 removed Alder-CA from the upstream trust bundle; rollout coincides with the first failures.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Opal production TLS incident",
  "attribute": "configuration change",
  "value": "Alder-CA removed in tb18"
}
```

Corrected atomic claims:

1. `support_resolution_conflict:change_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "bundle_change",
     "value": {
       "from": "tb17",
       "to": "tb18",
       "removed_issuer": "Alder-CA"
     }
   }
   ```

2. `support_resolution_conflict:change_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Opal production TLS incident",
     "attribute": "rollout_coincides_with_first_failures",
     "value": true
   }
   ```

## support_stale_runbook

### old_runbook

Supporting original passage:

> Nimbus v3 runbook: after rotating signing keys, restart the gateway pods to reload credentials.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "restart gateway pods"
}
```

Corrected atomic claims:

1. `support_stale_runbook:old_runbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v3 key rotation",
     "attribute": "credential_reload_instruction",
     "value": {
       "condition": "after signing-key rotation",
       "action": "restart gateway pods"
     }
   }
   ```

### kb_article

Supporting original passage:

> Knowledge base article for Nimbus v3: restart gateway pods after every signing-key rotation; keys are only read at startup.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "restart gateway pods"
}
```

Corrected atomic claims:

1. `support_stale_runbook:kb_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v3 key rotation",
     "attribute": "credential_reload_instruction",
     "value": {
       "condition": "after signing-key rotation",
       "action": "restart gateway pods"
     }
   }
   ```

2. `support_stale_runbook:kb_article:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v3 key rotation",
     "attribute": "keys_read_timing",
     "value": "startup only"
   }
   ```

### deployment_config

Supporting original passage:

> Nimbus v5 production config: key_reload_mode=watch; admin endpoint POST /admin/keys/refresh triggers immediate credential-cache refresh.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "POST /admin/keys/refresh"
}
```

Corrected atomic claims:

1. `support_stale_runbook:deployment_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5 production",
     "attribute": "key_reload_mode",
     "value": "watch"
   }
   ```

2. `support_stale_runbook:deployment_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5",
     "attribute": "credential_refresh_endpoint_effect",
     "value": {
       "method": "POST",
       "endpoint": "/admin/keys/refresh",
       "effect": "immediate credential-cache refresh"
     }
   }
   ```

### incident_record

Supporting original passage:

> Incident N-510 on v5: key rotation left one cache behind; POST /admin/keys/refresh reloaded the current key and authentication recovered without a rollout.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "POST /admin/keys/refresh"
}
```

Corrected atomic claims:

1. `support_stale_runbook:incident_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5",
     "attribute": "credential_refresh_incident_result",
     "value": {
       "incident": "N-510",
       "context": "key rotation left one cache behind",
       "request": {
         "method": "POST",
         "endpoint": "/admin/keys/refresh"
       },
       "effects": [
         "current key reloaded",
         "authentication recovered"
       ],
       "rollout_required": false
     }
   }
   ```

### service_state

Supporting original passage:

> Nimbus live state: version=5.2; admin keys refresh endpoint enabled; active key mount is present; process has not restarted since deployment.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "POST /admin/keys/refresh"
}
```

Corrected atomic claims:

1. `support_stale_runbook:service_state` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus live service",
     "attribute": "version",
     "value": "5.2"
   }
   ```

2. `support_stale_runbook:service_state:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus 5.2 live service",
     "attribute": "refresh_endpoint_enabled",
     "value": true
   }
   ```

3. `support_stale_runbook:service_state:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus 5.2 live service",
     "attribute": "active_key_mount_present",
     "value": true
   }
   ```

4. `support_stale_runbook:service_state:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus 5.2 live service",
     "attribute": "restarted_since_deployment",
     "value": false
   }
   ```

### change_record

Supporting original passage:

> Change N-492 migrated production to v5 watch-mode keys. Operators may force a refresh using POST /admin/keys/refresh.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "POST /admin/keys/refresh"
}
```

Corrected atomic claims:

1. `support_stale_runbook:change_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5 production",
     "attribute": "key_reload_mode",
     "value": "watch"
   }
   ```

2. `support_stale_runbook:change_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5",
     "attribute": "optional_refresh_instruction",
     "value": {
       "action": {
         "method": "POST",
         "endpoint": "/admin/keys/refresh"
       },
       "modality": "operators may force refresh"
     }
   }
   ```

### ticket

Supporting original passage:

> Support ticket template copied from the v3 KB: restart gateway pods after key rotation.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "restart gateway pods"
}
```

Corrected atomic claims:

1. `support_stale_runbook:ticket` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v3 key rotation",
     "attribute": "credential_reload_instruction",
     "value": {
       "condition": "after signing-key rotation",
       "action": "restart gateway pods"
     }
   }
   ```

### current_runbook

Supporting original passage:

> Nimbus v5 runbook: to refresh credentials after routine signing-key rotation, POST /admin/keys/refresh and confirm the loaded key ID.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Nimbus v5 key rotation",
  "attribute": "credential refresh action",
  "value": "POST /admin/keys/refresh"
}
```

Corrected atomic claims:

1. `support_stale_runbook:current_runbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Nimbus v5",
     "attribute": "credential_refresh_instruction",
     "value": {
       "condition": "after routine signing-key rotation",
       "action": {
         "method": "POST",
         "endpoint": "/admin/keys/refresh"
       },
       "verification": "confirm loaded key ID"
     }
   }
   ```

## support_ticket_reference_loop

### ticket

Supporting original passage:

> Ticket VG-88 resolution note: purge the ingest queue to clear backlog; cites KB-12. This ticket is also listed as precedent in incident VG-71.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "purge ingest queue"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:ticket` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "recommended_backlog_action",
     "value": "purge ingest queue"
   }
   ```

2. `support_ticket_reference_loop:ticket:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "ticket VG-88",
     "attribute": "cited_artifact",
     "value": "KB-12"
   }
   ```

3. `support_ticket_reference_loop:ticket:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "ticket VG-88",
     "attribute": "listed_as_precedent_in",
     "value": "incident VG-71"
   }
   ```

### kb_article

Supporting original passage:

> KB-12: clear Vega backlog by purging the ingest queue, following incident VG-71.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "purge ingest queue"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:kb_article` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "recommended_backlog_action",
     "value": "purge ingest queue"
   }
   ```

2. `support_ticket_reference_loop:kb_article:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "KB-12",
     "attribute": "cited_artifact",
     "value": "incident VG-71"
   }
   ```

### incident_record

Supporting original passage:

> Incident VG-71 retrospective, revised after VG-88: recommended action is to purge the ingest queue; evidence link points to ticket VG-88.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "purge ingest queue"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:incident_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "recommended_backlog_action",
     "value": "purge ingest queue"
   }
   ```

2. `support_ticket_reference_loop:incident_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "incident VG-71",
     "attribute": "revised_after",
     "value": "ticket VG-88"
   }
   ```

3. `support_ticket_reference_loop:incident_record:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "incident VG-71",
     "attribute": "evidence_link",
     "value": "ticket VG-88"
   }
   ```

### service_state

Supporting original passage:

> Vega service state: ingest consumer paused=true; queue depth=18000; storage health=ok; no corrupt messages reported. Resume operation is available.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "resume ingest consumer"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:service_state` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "consumer_paused",
     "value": true
   }
   ```

2. `support_ticket_reference_loop:service_state:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "queue_depth",
     "value": 18000
   }
   ```

3. `support_ticket_reference_loop:service_state:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "storage_health",
     "value": "ok"
   }
   ```

4. `support_ticket_reference_loop:service_state:claim:4` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "corrupt_messages_reported",
     "value": false
   }
   ```

5. `support_ticket_reference_loop:service_state:claim:5` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "resume_operation_available",
     "value": true
   }
   ```

### deployment_config

Supporting original passage:

> Deployment config: ingest consumer supports POST /consumers/ingest/resume; pause persists across restarts; queue purge discards pending records.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "resume ingest consumer"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:deployment_config` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "available_resume_endpoint",
     "value": {
       "method": "POST",
       "endpoint": "/consumers/ingest/resume"
     }
   }
   ```

2. `support_ticket_reference_loop:deployment_config:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "pause_persists_across_restarts",
     "value": true
   }
   ```

3. `support_ticket_reference_loop:deployment_config:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "purge_effect",
     "value": "pending records discarded"
   }
   ```

### runbook

Supporting original passage:

> Vega runbook: with consumer paused and storage healthy, resume the ingest consumer and observe queue drain before any destructive queue action.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "resume ingest consumer"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:runbook` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "backlog_recovery_instruction",
     "value": {
       "condition": {
         "consumer": "paused",
         "storage": "healthy"
       },
       "action": "resume ingest consumer",
       "verification": "observe queue drain",
       "ordering": "observe drain before any destructive queue action"
     }
   }
   ```

### monitoring_result

Supporting original passage:

> Monitoring probe: storage writes pass; consumer pause flag set; drain test on a resumed canary consumer processes queued records successfully.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "resume ingest consumer"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:monitoring_result` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "storage_writes_pass",
     "value": true
   }
   ```

2. `support_ticket_reference_loop:monitoring_result:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "consumer_paused",
     "value": true
   }
   ```

3. `support_ticket_reference_loop:monitoring_result:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "resumed_canary_result",
     "value": "queued records processed successfully"
   }
   ```

### change_record

Supporting original passage:

> Change VG-103 paused ingest consumer for maintenance; maintenance is complete and the recorded follow-up is to resume the consumer.

Original structured claim:

```json
{
  "entity_namespace": "operations",
  "entity": "Vega ingest backlog",
  "attribute": "recovery action",
  "value": "resume ingest consumer"
}
```

Corrected atomic claims:

1. `support_ticket_reference_loop:change_record` (retained original observation ID)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "maintenance_complete",
     "value": true
   }
   ```

2. `support_ticket_reference_loop:change_record:claim:2` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "recorded_followup_action",
     "value": "resume ingest consumer"
   }
   ```

3. `support_ticket_reference_loop:change_record:claim:3` (additional atomic fact)

   ```json
   {
     "entity_namespace": "operations",
     "entity": "Vega ingest backlog",
     "attribute": "pause_reason",
     "value": "maintenance"
   }
   ```

