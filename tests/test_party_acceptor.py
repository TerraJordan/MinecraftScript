"""tests/test_party_acceptor.py — очередь, таймаут, методы принятия."""

from types import SimpleNamespace

from party_acceptor import InviteJob, PartyAcceptor


def _event(event_type, data):
    return SimpleNamespace(type=event_type, timestamp="10:00:00", text="", data=data, raw="")


def test_log_chat_accept_sends_command():
    sent = []
    acceptor = PartyAcceptor(method="log_chat", send_command=sent.append,
                             focus_window=None, notify=lambda *a: None)
    acceptor.on_party_join_command(_event("party_join_command", {"player": "Steve"}))
    acceptor.process()
    assert sent == ["/party join Steve"]


def test_multiple_invites_go_to_queue():
    sent = []
    acceptor = PartyAcceptor(method="log_chat", send_command=sent.append, notify=lambda *a: None)
    acceptor.on_party_join_command(_event("party_join_command", {"player": "A"}))
    acceptor.on_party_join_command(_event("party_join_command", {"player": "B"}))
    assert len(acceptor.queue) == 2
    acceptor.process()                       # первое принято
    assert sent == ["/party join A"]
    acceptor._last_accept_at = 0             # снимаем паузу между принятиями
    acceptor.process()
    assert sent == ["/party join A", "/party join B"]


def test_expired_invite_is_dropped():
    sent = []
    acceptor = PartyAcceptor(method="log_chat", timeout_seconds=60,
                             send_command=sent.append, notify=lambda *a: None)
    job = InviteJob(player="Old", method="log_chat", command="/party join Old")
    job.received_at -= 120                   # пришло больше 60 секунд назад
    acceptor.queue.append(job)
    acceptor.process()
    assert sent == [] and len(acceptor.queue) == 0


def test_opencv_method_uses_clicker():
    clicks = []
    acceptor = PartyAcceptor(method="opencv",
                             opencv_click=lambda: (clicks.append(1), True)[1],
                             focus_window=None, notify=lambda *a: None)
    acceptor.on_party_invite(_event("party_invite", {"player": "Alex"}))
    acceptor.process()
    assert clicks == [1]


def test_queue_disabled_keeps_only_first():
    acceptor = PartyAcceptor(method="log_chat", queue_enabled=False,
                             send_command=lambda c: None, notify=lambda *a: None)
    acceptor.on_party_join_command(_event("party_join_command", {"player": "A"}))
    acceptor.on_party_join_command(_event("party_join_command", {"player": "B"}))
    assert len(acceptor.queue) == 1          # второе отклонено