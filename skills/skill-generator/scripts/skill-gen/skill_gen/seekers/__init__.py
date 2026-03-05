# Extracted subset of Skill_Seekers (https://github.com/ICEORY/Skill_Seekers)
# Only the modules actually used by skill-generator are included here
# to avoid carrying the full repository as a dependency.

from .md_scraper import MarkdownToSkillConverter
from .pdf_scraper import PDFToSkillConverter
from .adaptor_base import SkillAdaptor, SkillMetadata
