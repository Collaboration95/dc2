"""V1 container entrypoint, guarded by an absolute process watchdog.

python -m processing.v1_worker --deadline-epoch EPOCH --name TASK --max-empty-polls 2
"""

from processing.worker.finite import main

if __name__ == "__main__":
    main()
