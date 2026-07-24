import schedule as schedule_lib
from ainews import scheduler


def test_analysis_times_registered(monkeypatch):
    schedule_lib.clear()
    monkeypatch.setattr("ainews.pipeline.run_all", lambda conn, s: [])
    called = []
    import threading
    stop = threading.Event(); stop.set()  # 立即退出循环，只验证注册
    scheduler.start_scheduler(lambda: None, [], stop_event=stop,
                              analysis_job=lambda: called.append(1),
                              analysis_times=["08:00", "12:00"])
    daily = [j for j in schedule_lib.get_jobs() if j.at_time is not None]
    assert len(daily) == 2
    schedule_lib.clear()


def test_cleanup_job_registered_alongside_analysis(monkeypatch):
    schedule_lib.clear()
    monkeypatch.setattr("ainews.pipeline.run_all", lambda conn, s: [])
    import threading
    stop = threading.Event(); stop.set()  # 立即退出循环，只验证注册
    scheduler.start_scheduler(lambda: None, [], stop_event=stop,
                              analysis_job=lambda: None,
                              analysis_times=["08:00", "12:00"],
                              cleanup_job=lambda: None,
                              cleanup_time="03:30")
    daily = [j for j in schedule_lib.get_jobs() if j.at_time is not None]
    assert len(daily) == 3
    schedule_lib.clear()
