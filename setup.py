from setuptools import setup, find_packages
from pathlib import Path

here = Path(__file__).resolve().parent

README = (here / "README.md").read_text(encoding="utf-8")

setup(
    name='pyaptcom4',
    version='1.1',
    description='pyaptcom4 is python api for BINDER device ',
    long_description=README,
    packages=find_packages(),
    author="odjvnrij",
    author_email="odjvnrij72@outlook.com",
    url="https://github.com/odjvnrij/pyaptcom4",
    license="APACHE LICENSE, VERSION 2.0",
    python_requires=">=3.6",
)
