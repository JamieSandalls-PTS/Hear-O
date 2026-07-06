"""PyInstaller entry point. Running `python run_app.py` is equivalent to
`python -m app.main`, but gives PyInstaller a concrete script to freeze."""

from app.main import main

if __name__ == "__main__":
    main()
