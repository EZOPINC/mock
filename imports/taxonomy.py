"""Read-only, batch-loaded taxonomy resolution shared by preview and confirmation."""
import re
from hashlib import sha256
from django.utils.text import slugify
from django.core.exceptions import ValidationError

from exams.models import Subject, Part, Module, Chapter, Topic


def normalized(value):
    return " ".join(str(value).split()).casefold()


class TaxonomyCatalogue:
    models = {"subject": Subject, "part": Part, "module": Module, "chapter": Chapter, "topic": Topic}

    def __init__(self, *, locked=False):
        self.records, self.codes, self.ids = {}, {}, {}
        self.pending = []
        for kind, model in self.models.items():
            queryset = model.objects.order_by("pk")
            if locked:
                queryset = queryset.select_for_update()
            self.records[kind] = list(queryset)
            self.codes[kind] = {node.code: node for node in self.records[kind]}
            self.ids[kind] = {node.pk: node for node in self.records[kind]}

    def propose(self, kind, value, code, subject, nodes, errors):
        """Stage a named child; preview never writes to the database."""
        if not subject or errors:
            return None
        model = self.models[kind]
        parent_kind = next((field for field in model.parent_fields if field in nodes), None)
        parent = nodes[parent_kind] if parent_kind else subject
        key = f"{kind}:{parent_kind or 'subject'}:{parent.pk}:{normalized(value)}"
        digest = sha256(key.encode()).hexdigest()
        code = code or f"{kind.upper()}-{digest[:32]}"
        if any(normalized(node.code) == normalized(code) for node in self.records[kind]):
            errors.append(f"{kind.title()} code conflicts with an existing record.")
            return None
        node = model(name=value, code=code, subject=subject,
                     slug=(slugify(value)[:160] or kind) + "-" + digest[:16])
        if parent_kind:
            setattr(node, parent_kind, parent)
        try:
            for field in ("name", "code", "slug"):
                node._meta.get_field(field).clean(getattr(node, field), node)
        except ValidationError as error:
            errors.extend(error.messages)
            return None
        node.pk = -int(digest[:15], 16)
        self.pending.append((kind, node))
        self.records[kind].append(node)
        self.codes[kind][code] = node
        self.ids[kind][node.pk] = node
        return node

    def persist(self):
        """Called only after validation, inside the import transaction."""
        for kind, node in self.pending:
            for field in node.parent_fields:
                if getattr(node, field + "_id") is not None:
                    setattr(node, field + "_id", getattr(node, field).pk)
            node.pk = None
            node.full_clean()
            node.save()

    def lineage(self, kind, node):
        """Root-first nodes without following ORM relationships (no per-row queries)."""
        chain = [(kind, node)]
        while kind != "subject":
            parent_kind = next((field for field in ("chapter", "module", "part")
                                if getattr(node, field + "_id", None)), "subject")
            node = self.ids[parent_kind][getattr(node, parent_kind + "_id")]
            kind = parent_kind
            chain.append((kind, node))
        return list(reversed(chain))

    def path(self, kind, node):
        return " → ".join(f"{item.name} [{item.code}]" for _, item in self.lineage(kind, node))

    def resolve(self, values, selected, subject_map, topic_map):
        errors, nodes = [], {}
        for kind in self.models:
            code = values.get(kind + "_code", "").strip()
            if code:
                node = self.codes[kind].get(code)
                if node is None and (kind == "subject" or not values.get(kind, "").strip()):
                    errors.append(f"Unknown {kind}_code: {code}. Select an existing taxonomy code.")
                elif node is not None:
                    nodes[kind] = node

        def name_match(value, candidates, aliases, *, code_node=None):
            key = normalized(value)
            if key in aliases:
                return next((node for node in candidates if str(node.pk) == str(aliases[key])), None)
            if code_node is not None and normalized(code_node.name) == key:
                return code_node
            matches = [node for node in candidates if normalized(node.name) == key]
            return matches[0] if len(matches) == 1 else None

        subject = nodes.get("subject")
        raw_subject = values.get("subject", "").strip()
        if raw_subject or "" in subject_map:
            named = name_match(raw_subject, self.records["subject"], subject_map, code_node=subject)
            if named is None:
                errors.append("Subject is unresolved or ambiguous. Select an existing subject mapping.")
            elif subject is not None and named.pk != subject.pk:
                errors.append("subject_code conflicts with the subject name/mapping.")
            else:
                subject = named
        if subject is None and not raw_subject:
            roots = {node.subject_id for kind, node in nodes.items() if kind != "subject"}
            if len(roots) == 1:
                subject = self.ids["subject"].get(next(iter(roots)))
            if subject is None:
                subject = self.ids["subject"].get(selected.get("subject_id"))
            if subject is None:
                # Reuse the legacy fallback only if it already exists.
                candidates = [node for node in self.records["subject"] if normalized(node.name) == "unidentified"]
                subject = candidates[0] if len(candidates) == 1 else None
        if subject is None:
            errors.append("Subject is unresolved or ambiguous. Select an existing subject mapping.")
        else:
            if values.get("topic_code", "").strip() and selected.get("subject_id") and subject.pk != selected["subject_id"]:
                errors.append("topic_code conflicts with the subject selected on the import form.")
            for kind, node in nodes.items():
                root_id = node.pk if kind == "subject" else node.subject_id
                if root_id != subject.pk:
                    errors.append(f"{kind}_code does not belong to the resolved subject.")

        # Names follow the same normalized hierarchy as codes, without fuzzy matches.
        for kind in ("part", "module", "chapter"):
            value = values.get(kind, "").strip()
            if not value:
                continue
            candidates = [node for node in self.records[kind] if subject and node.subject_id == subject.pk]
            for other_kind, other in nodes.items():
                if other_kind in {"subject", kind}:
                    continue
                candidates = [node for node in candidates if
                    (other_kind, other.pk) in {(k, n.pk) for k, n in self.lineage(kind, node)} or
                    (kind, node.pk) in {(k, n.pk) for k, n in self.lineage(other_kind, other)}]
            named = name_match(value, candidates, {}, code_node=nodes.get(kind))
            if named is None and kind not in nodes and not any(normalized(node.name) == normalized(value) for node in candidates):
                named = self.propose(kind, value, values.get(kind + "_code", "").strip(), subject, nodes, errors)
            if named is not None and values.get(kind + "_code", "").strip() and named.code != values[kind + "_code"].strip():
                errors.append(f"{kind}_code conflicts with the {kind} name.")
            if named is None:
                errors.append(f"{kind.title()} is unresolved or ambiguous within the selected subject/ancestry. Use an existing name or stable code.")
            elif kind in nodes and nodes[kind].pk != named.pk:
                errors.append(f"{kind}_code conflicts with the {kind} name.")
            else:
                nodes[kind] = named

        context = {kind: node for kind, node in nodes.items() if kind != "subject"}
        topic = context.get("topic")
        raw_topic = values.get("topic", "").strip()
        if raw_topic and subject:
            candidates = [node for node in self.records["topic"] if node.subject_id == subject.pk]
            candidates = [node for node in candidates if all((kind, ancestor.pk) in
                {(k, n.pk) for k, n in self.lineage("topic", node)}
                for kind, ancestor in context.items() if kind != "topic")]
            key = normalized(values.get("subject", "") + " / " + values["topic"])
            aliases = {normalized(raw_topic): topic_map[key]} if key in topic_map else {}
            named = name_match(raw_topic, candidates, aliases, code_node=topic)
            if named is None and topic is None and not aliases and not any(normalized(node.name) == normalized(raw_topic) for node in candidates):
                named = self.propose("topic", raw_topic, values.get("topic_code", "").strip(), subject, nodes, errors)
            if named is not None and values.get("topic_code", "").strip() and named.code != values["topic_code"].strip():
                errors.append("topic_code conflicts with the topic name/mapping.")
            if named is None:
                errors.append("Topic is unresolved or ambiguous, or does not belong to the selected subject/ancestry. Select an existing topic mapping.")
            elif topic is not None and topic.pk != named.pk:
                errors.append("topic_code conflicts with the topic name/mapping.")
            else:
                topic = named
        if topic is None and not raw_topic and not values.get("topic_code", "").strip() and selected.get("topic_id"):
            topic = self.ids["topic"].get(selected["topic_id"])
            if topic is None:
                errors.append("Default topic is unresolved.")
        if topic is not None:
            context["topic"] = topic
            if subject is None or topic.subject_id != subject.pk:
                errors.append("Primary topic must belong to the resolved subject.")
        if context:
            deepest_kind = next(kind for kind in ("topic", "chapter", "module", "part") if kind in context)
            chain = {(kind, node.pk) for kind, node in self.lineage(deepest_kind, context[deepest_kind])}
            if any((kind, node.pk) not in chain for kind, node in context.items()):
                errors.append("Taxonomy codes do not form a valid ancestor path (skipped levels are allowed).")
            path = self.path(deepest_kind, context[deepest_kind])
        else:
            path = self.path("subject", subject) if subject else "Unresolved"
        secondary = {}
        for code in re.split(r"[;,|]", values.get("additional_topic_codes", "")):
            code = code.strip()
            if not code:
                continue
            node = self.codes["topic"].get(code)
            if node is None:
                errors.append(f"Unknown additional topic code: {code}.")
            elif subject is None or node.subject_id != subject.pk:
                errors.append(f"Additional topic {code} must belong to the resolved subject.")
            elif topic is None or node.pk != topic.pk:
                secondary[node.pk] = node
        if secondary and topic is None:
            errors.append("Secondary topics require an explicit primary topic (topic_code or an existing topic mapping).")
        return {"subject": subject, "topic": topic, "secondary_topics": list(secondary.values()),
                "taxonomy_path": path, "secondary_paths": [self.path("topic", node) for node in secondary.values()],
                "taxonomy_errors": errors}


def topic_identity(topic):
    return topic.pk if topic is not None else None
