"""
training/model_status.py <router|planner|student>

Wypisuje, czy dany wytrenowany model jest teraz AKTYWNY w GREGAI (wpis w .env, ważny
manifest, prompt i katalog narzędzi bez zmian, model zainstalowany w Ollamie), i kończy
się kodem 0 (tak) albo 1 (nie). Używa tego `install.sh --train`, żeby po przerwie nie
trenować od nowa modeli, które już są gotowe i aktualne (wymuszenie: FORCE_TRAIN=1).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from env_loader import load_env  # noqa: E402

load_env()

import router  # noqa: E402

CHECKS = {"router": router.router_status, "planner": router.planner_status, "student": router.student_status}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in CHECKS:
        print(f"użycie: model_status.py {'|'.join(CHECKS)}", file=sys.stderr)
        return 2
    status = CHECKS[sys.argv[1]]()
    print(f"{sys.argv[1]}: {'aktywny' if status['enabled'] else 'nieaktywny'} ({status['reason']})")
    return 0 if status["enabled"] else 1


if __name__ == "__main__":
    sys.exit(main())
