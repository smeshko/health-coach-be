"""TaskContext unit tests (E1·P3 TASK-001)."""

from app.core import TaskContext


def test_defaults():
    ctx = TaskContext(event={"k": "v"})
    assert ctx.event == {"k": "v"}
    assert ctx.nodes == {}
    assert ctx.metadata == {}
    assert ctx.should_stop is False


def test_update_node_merges_not_overwrites():
    ctx = TaskContext(event=None)
    ctx.update_node("NodeA", score=1)
    ctx.update_node("NodeA", label="x")
    assert ctx.nodes["NodeA"] == {"score": 1, "label": "x"}


def test_stop_workflow_sets_flag():
    ctx = TaskContext(event=None)
    assert ctx.should_stop is False
    ctx.stop_workflow()
    assert ctx.should_stop is True


def test_importable_from_app_core():
    from app.core import TaskContext as TC

    assert TC is TaskContext
