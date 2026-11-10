"""Read-only, batch-loaded taxonomy resolution shared by preview and confirmation."""
import re

from exams.models import Subject, Part, Module, Chapter, Topic


def normalized(value):
    return " ".join(str(value).split()).casefold()


class TaxonomyCatalogue:
    models = {"subject": Subject, "part": Part, "module": Module, "chapter": Chapter, "topic": Topic}

    def __init__(self, *, locked=False):
        self.records, self.codes, self.ids = {}, {}, {}
        for kind, model in self.models.items():
            queryset = model.objects.order_by("pk")
            if locked:
                queryset = queryset.select_for_update()
            self.records[kind] = list(queryset)
            self.codes[kind] = {node.code: node for node in self.records[kind]}
            self.ids[kind] = {node.pk: node for node in self.records[kind]}

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
                if node is None:
                    errors.append(f"Unknown {kind}_code: {code}. Select an existing taxonomy code.")
                else:
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
