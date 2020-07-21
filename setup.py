from setuptools import setup


setup(
   name="oauth_helper",
   version="0.1.1",
   description="A helper for Discord's oauth2 implementation",
   author='Blue',
   url="https://nqn.blue/",
   packages=["oauth_helper"],
   install_requires=["cachetools", "discord.py"]
)
