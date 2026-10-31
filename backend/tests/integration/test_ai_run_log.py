from sqlalchemy import text

from fairpool.modules.intake.run_log import PostgresAiRunLogger


async def test_ai_run_logger_writes_attempt_rows(db_session):
    logger = PostgresAiRunLogger()
    run_id = await logger.log(
        db_session,
        task="INTAKE",
        model="fictional-model",
        prompt_version="phase2-gemini-v3/1",
        input_hash="a" * 64,
        output={"clarification": None},
        ok=True,
        error=None,
        latency_ms=12,
        tokens_in=3,
        tokens_out=4,
    )
    row = (
        await db_session.execute(
            text(
                "SELECT task, model, prompt_version, input_hash, output, ok, error, "
                "latency_ms, tokens_in, tokens_out FROM ai_runs WHERE id=:id"
            ),
            {"id": run_id},
        )
    ).one()
    assert tuple(row) == (
        "INTAKE",
        "fictional-model",
        "phase2-gemini-v3/1",
        "a" * 64,
        {"clarification": None},
        True,
        None,
        12,
        3,
        4,
    )
