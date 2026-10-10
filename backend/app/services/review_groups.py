"""Build connected, pending visual-review groups without changing audit rows."""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PendingReviewLink:
    review_id: int
    task_id: int
    pair_id: int
    version: int
    image_new_id: int
    image_match_id: int


@dataclass(frozen=True)
class PendingReviewGroup:
    task_id: int
    links: tuple[PendingReviewLink, ...]
    image_ids: tuple[int, ...]

    @property
    def seed_review_id(self) -> int:
        return min(link.review_id for link in self.links)


def group_pending_review_links(links: Iterable[PendingReviewLink]) -> list[PendingReviewGroup]:
    """Return connected components of pending review relations, per task.

    The links remain directed audit records.  Grouping treats their two image
    endpoints as an undirected relation solely for the review screen, so
    mirrored rows such as A→B and B→A appear together exactly once.
    """
    by_task: dict[int, list[PendingReviewLink]] = {}
    for link in links:
        by_task.setdefault(link.task_id, []).append(link)

    groups: list[PendingReviewGroup] = []
    for task_id, task_links in by_task.items():
        by_image: dict[int, set[int]] = {}
        link_by_id = {link.review_id: link for link in task_links}
        for link in task_links:
            by_image.setdefault(link.image_new_id, set()).add(link.review_id)
            by_image.setdefault(link.image_match_id, set()).add(link.review_id)

        remaining = set(link_by_id)
        while remaining:
            first_id = min(remaining)
            pending_link_ids = [first_id]
            component_link_ids: set[int] = set()
            component_images: set[int] = set()
            while pending_link_ids:
                review_id = pending_link_ids.pop()
                if review_id in component_link_ids:
                    continue
                component_link_ids.add(review_id)
                remaining.discard(review_id)
                link = link_by_id[review_id]
                for image_id in (link.image_new_id, link.image_match_id):
                    if image_id in component_images:
                        continue
                    component_images.add(image_id)
                    pending_link_ids.extend(by_image[image_id] - component_link_ids)
            component_links = tuple(sorted((link_by_id[row_id] for row_id in component_link_ids), key=lambda row: row.review_id))
            groups.append(PendingReviewGroup(task_id=task_id, links=component_links, image_ids=tuple(sorted(component_images))))

    return sorted(groups, key=lambda group: (group.task_id, group.seed_review_id))
