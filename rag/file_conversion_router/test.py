import pprint
json_dict = {'key_concept': [{'explanation_points': {'text': 'A lambda expression is a way to define an anonymous function (procedure) in Scheme or other Lisp-like languages. It has the form (lambda (<formal-parameters>) <body>), and evaluates to a procedure object.', 'type': 'Definition'}, 'key_concept': 'Lambda Expression'}, {'explanation_points': {'text': "A LambdaProcedure represents user-defined functions created by lambda expressions. It stores the function's formal parameters, its body (the code to execute), and the environment (frame) in which it was defined.", 'type': 'How it Works'}, 'key_concept': 'LambdaProcedure (class)'}, {'explanation_points': {'text': 'A frame is an environment record that holds variable bindings (name-value pairs). Frames can form a tree structure via parent links to model nested scopes. They are used during evaluation to keep track of variable meanings.', 'type': 'Definition'}, 'key_concept': 'Frame (Environment Frame)'}, {'explanation_points': {'text': 'A Scheme expression is any form that can be evaluated by the Scheme interpreter. It can be a primitive (number, symbol), or a combination (a list where the first element is an operator and the rest are arguments).', 'type': 'Definition'}, 'key_concept': 'Scheme Expression'}, {'explanation_points': {'text': 'A Scheme list is a linked data structure used to represent sequences. In Scheme, both code and data can be represented as lists, making programs easily manipulable as data.', 'type': 'Definition'}, 'key_concept': 'Scheme List'}, {'explanation_points': {'text': 'This concept allows a program to construct, manipulate, and even evaluate other programs (or itself). It’s foundational in languages like Scheme, where code and data share the same structure (lists).', 'type': "Why it's Important"}, 'key_concept': 'Programs as Data'}, {'explanation_points': {'text': 'By recursively traversing an expression tree and applying transformations (like flattening nested multiplication calls), a program can produce a simpler, equivalent expression. This demonstrates metaprogramming abilities in Scheme.', 'type': 'How it Works'}, 'key_concept': 'Automatic Code Simplification (flatten-nested-*)'}, {'explanation_points': {'text': "print_evals is a procedure that, given an arithmetic Scheme expression, prints each subexpression as it's evaluated along with its resulting value. This helps visualize the evaluation process, showing order and intermediate values.", 'type': 'How it Works'}, 'key_concept': 'print_evals Procedure'}], 'titles_with_levels': [{'level_of_title': 1, 'title': 'Programs as Data'}, {'level_of_title': 1, 'title': 'Announcements'}, {'level_of_title': 1, 'title': 'Lambda Expressions'}, {'level_of_title': 1, 'title': 'Frames and Environments'}, {'level_of_title': 1, 'title': 'Programs as Data'}, {'level_of_title': 2, 'title': 'A Scheme Expression is a Scheme List'}, {'level_of_title': 2, 'title': 'Discussion Question: Automatically Simplifying Code'}, {'level_of_title': 2, 'title': 'Discussion Question: Printing Evaluations'}]}
key_concepts_list = json_dict['key_concept']
dummy_concept = []
for concept in key_concepts_list:
    key_concept = concept['key_concept']
    type_ = concept["explanation_points"]['type']
    text = concept['explanation_points']['text']
    dummy_concept.append((key_concept, type_, text))
print(dummy_concept)

    page = Page(pagename="TestPage", content=content, filetype="pdf", page_url="http://example.com",mapping_json_path=Path("/Users/yyk956614/tai/rag/output/md/01-Welcome_1pp/01-Welcome_1pp_content_list.json"))

    page.page_seperate_to_segments()
    page.tree_print()
    original_recursive_separate = page.recursive_separate
    page.recursive_separate = lambda text, token_limit=400: original_recursive_separate(text, token_limit=400)
    chunks = page.tree_segments_to_chunks()

    for idx, chunk in enumerate(chunks, start=1):
        print(f"Chunk {idx}:")
        print("Title:", chunk.titles)
        print("Page Num:", chunk.page_num)
        print("Content snippet:", chunk.content[:100], "...")
        print("-" * 40)

if __name__ == "__main__":
    test_merge_functionality()