try:
    from .parser import parse_someip_pcap
except ImportError:
    from parser import parse_someip_pcap