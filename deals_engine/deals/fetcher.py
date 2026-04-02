from .sources.csv_feed import CsvFeedSource


def get_sources(source_name: str, csv_path: str):
    if source_name == "csv":
        return [CsvFeedSource(csv_path)]
    raise ValueError(f"Unsupported DEALS_SOURCE: {source_name}")
