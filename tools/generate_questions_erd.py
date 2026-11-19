"""Generate schema-only Questions ERD artifacts. Run from the project Python env."""
from datetime import date
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.apps import apps
from django.db import connection


def main():
    core = list(apps.get_app_config('questions').get_models())
    consumers = sorted({model for model in apps.get_models(include_auto_created=True)
                        if not model._meta.proxy and model not in core and any(
                            field.is_relation and field.remote_field.model in core
                            for field in model._meta.local_fields)}, key=lambda model: model._meta.label)
    taxonomy = [apps.get_model('exams', name) for name in (
        'Subject', 'Part', 'Module', 'Submodule', 'Chapter', 'Topic', 'ExamAuthority', 'Exam', 'ExamStage')]
    mock_models = list(apps.get_app_config('mock_tests').get_models())
    mock_context = [model for model in mock_models if model not in consumers]
    models = core + taxonomy + consumers + mock_context
    tables, edges, mismatches = [], [], []
    with connection.cursor() as cursor:
        for model in models:
            table = model._meta.db_table
            actual = connection.introspection.get_table_description(cursor, table)
            constraints = connection.introspection.get_constraints(cursor, table)
            columns = []
            actual_columns = {field.name for field in actual}
            actual_nullable = {field.name: field.null_ok for field in actual}
            expected_columns = {field.column for field in model._meta.concrete_fields}
            if actual_columns != expected_columns:
                mismatches.append(f'{table}: model/database column mismatch')
            types = {}
            if connection.vendor == 'postgresql':
                cursor.execute('SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped', [table])
                types = dict(cursor.fetchall())
            for field in model._meta.concrete_fields:
                if actual_nullable.get(field.column) != field.null:
                    mismatches.append(f'{table}.{field.column}: database nullability mismatch')
                target = None
                policy = None
                if field.is_relation:
                    target = field.remote_field.model._meta.db_table
                    policy = field.remote_field.on_delete.__name__
                    edge = {'child': table, 'parent': target, 'column': field.column,
                            'target_column': field.target_field.column, 'nullable': field.null,
                            'unique': field.unique, 'on_delete': policy}
                    edges.append(edge)
                    if not any(value.get('foreign_key') == (target, field.target_field.column)
                               and value['columns'] == [field.column] for value in constraints.values()):
                        mismatches.append(f'{table}.{field.column}: missing/mismatched database FK')
                columns.append({'column': field.column, 'type': types.get(field.column, field.db_type(connection)),
                                'nullable': field.null, 'pk': field.primary_key, 'unique': field.unique,
                                'target': target, 'on_delete': policy,
                                'blank': field.blank, 'choices': list(field.flatchoices) if field.choices else []})
            checks, indexes, triggers = [], [], []
            if connection.vendor == 'postgresql':
                cursor.execute('SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=%s::regclass ORDER BY conname', [table])
                checks = [{'name': name, 'definition': definition} for name, definition in cursor.fetchall()]
                cursor.execute('SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename=%s ORDER BY indexname', [table])
                indexes = [{'name': name, 'definition': definition} for name, definition in cursor.fetchall()]
                cursor.execute('SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal ORDER BY tgname', [table])
                triggers = [{'name': name, 'definition': definition} for name, definition in cursor.fetchall()]
            tables.append({'table': table, 'model': model._meta.label,
                           'group': 'core' if model in core else 'taxonomy' if model in taxonomy else 'consumer' if model in consumers else 'mock',
                           'columns': columns, 'constraints': checks, 'indexes': indexes, 'triggers': triggers})
    if mismatches:
        raise RuntimeError('\n'.join(mismatches))
    m2m = [{'owner': model._meta.db_table, 'field': field.name,
            'target': field.remote_field.model._meta.db_table,
            'through': field.remote_field.through._meta.db_table}
           for model in core for field in model._meta.local_many_to_many]
    verified_on = date.today().isoformat()
    schema = {'scope': 'Questions module, taxonomy, direct inbound FK consumers and mock configurations',
              'verified_on': verified_on,
              'tables': tables, 'relationships': edges, 'many_to_many': m2m,
              'verification': 'All listed model columns and foreign keys match the local database schema.'}
    destination = ROOT / 'docs' / 'erd'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'questions-schema.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    panels = {
        'questions-core': [table['table'] for table in tables if table['group'] == 'core'] + [
            'exams_subject', 'exams_topic', 'exams_exam'],
        'questions-taxonomy': [table['table'] for table in tables if table['group'] == 'taxonomy'],
        'questions-consumers': [table['table'] for table in tables if table['group'] == 'consumer'] + [
            'questions_question', 'questions_questionrevision'],
        'questions-mocks': [model._meta.db_table for model in mock_models] + [
            'questions_question', 'questions_questionrevision', 'exams_exam'],
    }
    reference = ['# Questions module ERD', '',
                 f'Source and local PostgreSQL schema verified on {verified_on}. Schema metadata only; no application records were read.', '',
                 '[Open the offline interactive diagram](questions-erd.html) · [Machine-readable schema](questions-schema.json)', '',
                 f'All columns are shown for {len(core)} Questions-owned tables, {len(taxonomy)} taxonomy/catalogue tables, '
                 f'{len(consumers)} direct inbound consumer tables, and {len(mock_context)} further mock tables. '
                 'Other referenced tables appear as boundary keys where needed.', '',
                 'PK = primary key; FK = foreign key; nullable = SQL NULL permitted. Cardinality is derived from physical FKs and uniqueness, not workflow assumptions. Arrows in HTML point from child FK to parent. Mermaid uses crow’s-foot cardinality.', '',
                 'Django `on_delete` policy and SQL FK action are different: the policies below describe ORM deletion; actual PostgreSQL constraints/indexes/triggers are listed separately. `blank` and choices are application validation metadata, not database nullability.', '',
                 '## Schema changes since the previous ERD', '',
                 '- `questions.0006_question_kind` adds `Question.question_kind` with Logical, Static and Unclassified values.',
                 '- `mock_tests.0009_question_kind` adds the Any, Logical or Static filter to `SectionSelectionRule`. Any is stored as an empty string.',
                 '- `exams.0011_default_mock_language` adds `Exam.default_mock_language`. It sets English for WBCS and Bengali for the other WBPSC exams.',
                 '', '## Relationships to review', '',
                 '- Question is the shared master identity. Its current_revision_id and published_revision_id are nullable FK pointers, not unique/one-to-one columns. Each pointed-to revision must belong to that master (workflow validation).',
                 '- QuestionRevision stores the primary language code and shared answer, difficulty and version metadata. QuestionTranslation stores immutable per-revision text, options and explanations. Its correct_answer property reads the revision answer key.',
                 '- Question.topic_id mirrors the primary QuestionTopic tag. The pair (question_id, topic_id) is unique; a partial unique index allows at most one primary per question. Deferred database triggers require a primary tag matching the pointer whenever tags exist. Unclassified questions may have neither.',
                 '- Question.topics, Question.exams and Question.sources are M2M fields backed by the three explicit join tables shown. There are no additional implicit M2M tables for these fields.',
                 '- QuestionSourceReference has page/source-number metadata and no unique Question/Source pair constraint. Multiple references for one pair are possible. QuestionSource document/name fields are not unique.',
                 '- PaperQuestion, AttemptQuestion and PracticeQuestion pin a revision alongside the master Question. ImportedQuestion, ManualRuleQuestion and SavedQuestion reference the master. SavedQuestion.question uses CASCADE; all other direct inbound Question/Revision FKs use PROTECT.',
                 '- A subject is shared across exams; there is no direct Subject/Exam join. QuestionExam establishes membership. Taxonomy nodes store a subject anchor plus at most one immediate parent; intermediate levels may be skipped. Submodule requires Module. Legacy Topics may lack a Chapter.',
                 '- JSON/JSONB columns contain snapshots or audit metadata; their internal values are not physical FK relationships and are not drawn as such.',
                 '- GeneralQuestionBatch and RevisionSession are proxies, not additional tables. Generic admin log references are not database FKs to Question.', '',
                 '## ERD diagrams', '']
    for name, included in panels.items():
        visible = set(included)
        relevant = [edge for edge in edges if edge['child'] in visible and (
            edge['parent'] in visible or name in {'questions-consumers', 'questions-mocks'})]
        boundaries = sorted({edge['parent'] for edge in relevant} - visible)
        lines = ['erDiagram']
        for table in tables:
            if table['table'] not in visible:
                continue
            lines.append('    ' + table['table'] + ' {')
            for column in table['columns']:
                dtype = re.sub(r'[^a-zA-Z0-9_]', '_', column['type'])
                keys = ','.join(key for key, value in [('PK', column['pk']), ('FK', bool(column['target'])), ('UK', column['unique'] and not column['pk'])] if value)
                note = 'NULL' if column['nullable'] else 'NOT_NULL'
                lines.append(f'        {dtype} {column["column"]}' + (f' {keys}' if keys else '') + f' "{note}"')
            lines.append('    }')
        for table in boundaries:
            lines.extend([f'    {table} {{', '        bigint id PK "BOUNDARY_ONLY"', '    }'])
        for edge in relevant:
            parent_end = 'o|' if edge['nullable'] else '||'
            child_end = 'o|' if edge['unique'] else 'o{'
            lines.append(f'    {edge["parent"]} {parent_end}..{child_end} {edge["child"]} : "{edge["column"]}"')
        diagram = '\n'.join(lines) + '\n'
        (destination / (name + '.mmd')).write_text(diagram, encoding='utf-8')
        reference.extend(['### ' + name.replace('questions-', '').title(), '', '```mermaid', diagram.rstrip(), '```', ''])
    reference.extend(['## Complete column and integrity reference', ''])
    for table in tables:
        reference.extend([f'### {table["table"]}', '', f'Model: `{table["model"]}` · Group: {table["group"]}', '',
                          '| Column | SQL type | Key | Nullable | Reference / ORM deletion |', '|---|---|---|---|---|'])
        for column in table['columns']:
            keys = ', '.join(key for key, value in [('PK', column['pk']), ('FK', bool(column['target'])), ('unique', column['unique'] and not column['pk'])] if value)
            target = f'{column["target"]} / {column["on_delete"]}' if column['target'] else ''
            reference.append(f'| {column["column"]} | {column["type"]} | {keys} | {column["nullable"]} | {target} |')
        for label in ('constraints', 'indexes', 'triggers'):
            if table[label]:
                reference.extend(['', '<details><summary>Database ' + label + '</summary>', '', '```sql',
                                  *[row['name'] + ': ' + row['definition'] for row in table[label]], '```', '', '</details>'])
        reference.append('')
    reference.extend(['## Regenerate', '', '`python tools/generate_questions_erd.py`', '',
                      'Uses the configured local database to verify schema metadata. No migrations, application data writes or record exports. Regenerate after schema changes.', ''])
    (destination / 'questions-erd.md').write_text('\n'.join(reference), encoding='utf-8')
    template = (ROOT / 'tools' / 'questions_erd_template.html').read_text(encoding='utf-8')
    (destination / 'questions-erd.html').write_text(template.replace('__VERIFIED_ON__', verified_on)
                                                   .replace('__SCHEMA__', json.dumps(schema, ensure_ascii=False).replace('<', '\\u003c')),
                                                   encoding='utf-8')
    print(f'Generated Questions ERD: {len(core)} owned tables, {len(taxonomy)} taxonomy tables, {len(consumers)} direct inbound consumers, {len(mock_context)} additional mock tables; {sum(len(table["columns"]) for table in tables)} columns and {len(edges)} FKs verified.')


if __name__ == '__main__':
    main()
