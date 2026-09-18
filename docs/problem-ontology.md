# Problem ontology v1

The ontology describes **what kind of workflow problem is occurring**. It is
separate from observation classification, which describes the evidential nature
of a report (`WORKFLOW_GAP`, `TEMPORARY_INCIDENT`, `SUPPORT_QUESTION`, and so on).

Every newly extracted positive observation carries both:

```text
problem_type      evidence/report classification
problem_family    workflow-problem family
ontology_version  problem-ontology-v1
```

Historical observations may temporarily have a null family. They must be assigned
through an explicit versioned classification rather than silently inferred during
a schema migration.

## Families

| Family | Scope |
|---|---|
| `MANUAL_DATA_ENTRY` | Re-keying, copying, or manually transferring information |
| `RECONCILIATION` | Comparing records and resolving mismatches |
| `INTEGRATION` | Systems or data flows that do not connect reliably |
| `DOCUMENT_COLLECTION` | Requesting, receiving, and organizing documents |
| `REPORTING` | Producing or maintaining recurring reports |
| `SCHEDULING` | Allocating people, resources, appointments, or shifts |
| `APPROVAL` | Review, sign-off, and authorization workflows |
| `COMMUNICATION` | Operational coordination and information exchange |
| `MIGRATION` | Moving data or workflows between systems |
| `COMPLIANCE` | Work created by regulatory or policy obligations |
| `HANDOVER` | Transferring responsibility or operational context |
| `ERROR_CORRECTION` | Finding and repairing erroneous records or outcomes |
| `SEARCH_RETRIEVAL` | Locating required information or artifacts |
| `MONITORING` | Observing state, events, thresholds, or exceptions |
| `PROCUREMENT` | Sourcing, evaluating, and purchasing inputs |
| `PAYMENTS` | Collecting, sending, allocating, or tracking payments |
| `INVENTORY` | Tracking stock, assets, or materials |
| `CUSTOMER_MANAGEMENT` | Managing customer records and service workflows |
| `WORKFORCE` | Staffing, employee operations, and labor administration |
| `OTHER` | Evidence-backed problems not represented above |

`OTHER` is an explicit reviewed classification, not a substitute for missing
information. If no classification was performed, the stored family remains null.

## Versioning and evaluation

The enum values are persisted and therefore cannot be renamed without a schema
and ontology migration. Detection benchmark positives require a valid family;
evaluation reports family accuracy separately from observation-type accuracy.

Source-performance snapshots aggregate observations by family. This enables
problem-specific source routing without declaring an entire community universally
good or bad. These metrics remain sample-size dependent and are not opportunity or
success scores.
