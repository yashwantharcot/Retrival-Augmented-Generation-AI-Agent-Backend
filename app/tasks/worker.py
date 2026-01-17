# app/tasks/worker.py
from fastapi import BackgroundTasks

def run_task(task_func, background_tasks: BackgroundTasks = None, *args, **kwargs):
    if background_tasks:
        background_tasks.add_task(task_func, *args, **kwargs)
        return "Task scheduled in background"
    return task_func(*args, **kwargs)

