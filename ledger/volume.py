def total_liters(segments):
    '''Aggregate confirmed segment volumes in exact integer liters.'''
    return sum(segment.liters for segment in segments)
