def post_process_search_queries_ko(search_queries_ko, subject, topic, element_verbatim):
    # Remove queries equal to the topic '국제법' or only containing that word
    filtered_queries = [query for query in search_queries_ko if query != '국제법']

    # Ensure at least 6 queries are present
    if len(filtered_queries) < 6:
        required_queries = 6 - len(filtered_queries)
        # Generate additional queries using the provided function
        additional_queries = build_search_query(subject, topic, element_verbatim)
        # Extract keywords from element_verbatim
        keywords = extract_keywords(element_verbatim)
        filtered_queries.extend(keywords[:required_queries])

    return filtered_queries
