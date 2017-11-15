from setuptools import setup

setup(
    name='cvrparser',
    version=0.1,
    url='https://github.com/gronlund/cvrdata',
    description=('A module for fetching Central Business Register data from the Danish Business Authority'),
    author='Allan Gronlund',
    author_email='allan.g.joergensen@gmail.com',
    license='MIT',
    packages=['cvrparser'],
    install_requires=[
        'SQLAlchemy>=1.1.14',
        'elasticsearch1>=1.10.0',
        'elasticsearch1-dsl>=0.0.12',
        'mysqlclient>=1.3.12',
        'numpy>=1.13.3',
        'python-dateutil>=2.6.1',
        'python_Levenshtein>=0.12.0',
        'pytz>=2017.3',
        'requests',
        'ujson>=1.35'
    ],
)