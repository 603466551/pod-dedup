from app.services.review_groups import PendingReviewLink, group_pending_review_links


def _link(review_id: int, new_id: int, match_id: int, task_id: int = 1) -> PendingReviewLink:
    return PendingReviewLink(review_id=review_id, task_id=task_id, pair_id=review_id, version=1, image_new_id=new_id, image_match_id=match_id)


def test_mirrored_and_chain_candidate_rows_form_one_group() -> None:
    groups = group_pending_review_links([
        _link(5, 10, 20), _link(6, 20, 10), _link(7, 10, 30),
        _link(8, 30, 10), _link(9, 20, 30), _link(10, 30, 20),
    ])

    assert len(groups) == 1
    assert groups[0].image_ids == (10, 20, 30)
    assert [link.review_id for link in groups[0].links] == [5, 6, 7, 8, 9, 10]


def test_groups_do_not_cross_tasks_or_disconnected_components() -> None:
    groups = group_pending_review_links([_link(1, 1, 2), _link(2, 3, 4), _link(3, 1, 2, task_id=2)])

    assert [(group.task_id, group.image_ids) for group in groups] == [(1, (1, 2)), (1, (3, 4)), (2, (1, 2))]
